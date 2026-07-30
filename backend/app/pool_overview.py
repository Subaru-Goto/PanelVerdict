"""Pool QC: does the persisted pool match the priors it was drawn from?

Population-level only, never per-persona. Two panels, and both compare the
pool against **our own** seed distributions, so they catch a broken sampler rather
than an unrealistic pool.

The Big Five panel is the one worth reading carefully. Each persona is drawn from
`MVN(μ(age, gender), Σ)` and μ moves with age and gender, so over a pool the law of
total covariance gives `E[X] = E[μ]` and `Cov(X) = Σ + Cov(μ)`. Checking against
`mean 0, sd 1` would therefore fail a *correct* sampler, and by a margin that grows
with pool size — the gap is fixed while its standard error shrinks as `1/sqrt(n)`.
"""

import argparse
import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import psycopg

from app.bigfive import SIGMA, mu_for
from app.config import settings
from app.panel import render_persona_prompt
from app.persistence import load_pool
from app.sampler import JointCell, load_joint
from app.schemas import BigFive, EducationLevel, Locale, Persona

_DIMENSIONS = ("age_band", "gender", "education", "income_quintile")
_TRAITS = tuple(BigFive.model_fields)


@dataclass(frozen=True)
class MarginalDeviation:
    """One demographic category: what the joint table implies vs. what was drawn.

    `z` is the gap in units of its own sampling error, `sqrt(p(1-p)/n)` — derived
    rather than compared against a chosen pass mark. A category the table gives no
    weight at all has no sampling error to speak of, so drawing one is impossible
    rather than unlikely and `z` is infinite.
    """

    country: str
    dimension: str
    category: str
    target: float
    realized: float
    z: float


@dataclass(frozen=True)
class MomentComparison:
    """One trait's first two moments against the priors, conditioned on the pool's
    realized age/gender mix."""

    trait: str
    expected_mean: float
    realized_mean: float
    mean_z: float
    expected_sd: float
    realized_sd: float
    sd_z: float


@dataclass(frozen=True)
class CorrelationDeviation:
    trait_a: str
    trait_b: str
    expected: float
    realized: float


def age_band_of(age: int, bands: tuple[str, ...]) -> str:
    """Map a concrete age back to the joint-table band it was drawn from.

    Ages are resolved uniformly within a band at sample time, so the band is where
    the comparison has to happen — a concrete age has no target to be checked
    against.
    """
    for band in bands:
        if band.endswith("+"):
            if age >= int(band[:-1]):
                return band
        else:
            low, high = (int(part) for part in band.split("-"))
            if low <= age <= high:
                return band
    raise ValueError(f"no age band in {bands} contains age {age}")


def _proportions(cells: list[JointCell]) -> dict[str, dict[str, float]]:
    total = sum(cell.weight for cell in cells)
    out: dict[str, dict[str, float]] = {d: defaultdict(float) for d in _DIMENSIONS}
    for cell in cells:
        share = cell.weight / total
        out["age_band"][cell.age_band] += share
        out["gender"][cell.gender] += share
        out["education"][cell.education.value] += share
        out["income_quintile"][str(cell.income_quintile)] += share
    return out


def _realized(
    personas: list[Persona], bands: tuple[str, ...]
) -> dict[str, dict[str, float]]:
    """Counted as integers and divided once, so a pool that matches its table
    exactly reports exactly zero rather than accumulated float dust."""
    counts: dict[str, dict[str, int]] = {d: defaultdict(int) for d in _DIMENSIONS}
    for persona in personas:
        counts["age_band"][age_band_of(persona.age, bands)] += 1
        counts["gender"][persona.gender] += 1
        counts["education"][persona.education.value] += 1
        counts["income_quintile"][str(persona.income_quintile)] += 1
    n = len(personas)
    return {
        dimension: {category: count / n for category, count in categories.items()}
        for dimension, categories in counts.items()
    }


_CATEGORY_ORDER: dict[str, tuple[str, ...]] = {
    "education": tuple(level.value for level in EducationLevel),
}


def _category_sort_key(dimension: str, category: str) -> tuple[int, str]:
    """Report order: numeric where the category is a number or a band, otherwise the
    dimension's own declared order. Alphabetical would put education's ISCED levels
    in the right order only by luck of their spelling."""
    if dimension in ("age_band", "income_quintile"):
        return (int(category.rstrip("+").split("-")[0]), "")
    if dimension in _CATEGORY_ORDER:
        return (_CATEGORY_ORDER[dimension].index(category), "")
    return (0, category)


def demographic_deviations(
    personas: list[Persona], tables: dict[str, list[JointCell]]
) -> list[MarginalDeviation]:
    """Realized demographic marginals against the joint tables that produced them.

    Marginals rather than cells: a country table has 240 cells and even the full
    5,000-persona pool leaves about seven draws per cell, so a cell-level test would
    be reading noise.

    Compared **per country**, because that is the unit a joint table asserts. Pooling
    the countries first would let opposite errors cancel — a US pool skewed old
    against a JP pool skewed young reports a clean overall age marginal that neither
    country's table supports.
    """
    if not personas:
        raise ValueError("cannot audit an empty pool")
    by_country: dict[str, list[Persona]] = defaultdict(list)
    for persona in personas:
        by_country[persona.country.value].append(persona)

    deviations = []
    for country in sorted(by_country):
        members = by_country[country]
        n = len(members)
        cells = tables[country]
        bands = tuple(dict.fromkeys(cell.age_band for cell in cells))
        target = _proportions(cells)
        realized = _realized(members, bands)
        for dimension in _DIMENSIONS:
            categories = set(target[dimension]) | set(realized[dimension])
            for category in sorted(
                categories, key=lambda c: _category_sort_key(dimension, c)
            ):
                expected = target[dimension].get(category, 0.0)
                observed = realized[dimension].get(category, 0.0)
                se = math.sqrt(expected * (1 - expected) / n)
                if se:
                    z = (observed - expected) / se
                else:
                    # p of 0 or 1 admits no sampling error, so any gap is a draw the
                    # table calls impossible — the loudest thing this panel can find,
                    # and a plain 0.0 here would have rendered it as a perfect score.
                    z = 0.0 if observed == expected else math.inf
                deviations.append(
                    MarginalDeviation(
                        country=country,
                        dimension=dimension,
                        category=category,
                        target=expected,
                        realized=observed,
                        z=z,
                    )
                )
    return deviations


def _scores(personas: list[Persona]) -> np.ndarray:
    return np.array([[getattr(p.big_five, t) for t in _TRAITS] for p in personas])


def expected_moments(personas: list[Persona]) -> tuple[np.ndarray, np.ndarray]:
    """Mean and covariance the pool's own demographic mix implies.

    `Cov(X) = Σ + Cov(μ)` — the between-cell spread of μ adds to Σ's within-cell
    spread, so a pool spanning several age/gender cells is expected to be wider than
    Σ alone. Conditioning on the realized mix, rather than on the joint table, keeps
    this panel independent of whether the demographic panel passed.
    """
    mus = np.array([mu_for(p.age, p.gender) for p in personas])
    return mus.mean(axis=0), np.array(SIGMA) + np.cov(mus.T, bias=True)


def bigfive_comparisons(personas: list[Persona]) -> list[MomentComparison]:
    """Per-trait mean and sd against the conditional priors, in standard errors."""
    if len(personas) < 2:
        raise ValueError("cannot audit a pool of fewer than 2 personas")
    n = len(personas)
    expected_mean, expected_cov = expected_moments(personas)
    expected_sd = np.sqrt(np.diag(expected_cov))
    scores = _scores(personas)
    realized_mean, realized_sd = scores.mean(axis=0), scores.std(axis=0, ddof=1)

    # Conditioning on the realized mix fixes μ, so the sampling error of the mean is
    # the *within-cell* spread alone: Var(mean) = Σ_jj/n. Dividing by the marginal sd
    # would carry Cov(μ) into the denominator and quietly deflate every mean_z.
    mean_se = np.sqrt(np.diag(np.array(SIGMA)) / n)
    # sd/sqrt(2n) is the normal-theory error of a sample sd applied to what is really
    # a mixture of normals — an approximation, and the weaker of the two rows.
    sd_se = expected_sd / math.sqrt(2 * n)

    return [
        MomentComparison(
            trait=trait,
            expected_mean=float(expected_mean[i]),
            realized_mean=float(realized_mean[i]),
            mean_z=float((realized_mean[i] - expected_mean[i]) / mean_se[i]),
            expected_sd=float(expected_sd[i]),
            realized_sd=float(realized_sd[i]),
            sd_z=float((realized_sd[i] - expected_sd[i]) / sd_se[i]),
        )
        for i, trait in enumerate(_TRAITS)
    ]


def _to_correlation(cov: np.ndarray) -> np.ndarray:
    sd = np.sqrt(np.diag(cov))
    return cov / np.outer(sd, sd)


def correlation_deviations(personas: list[Persona]) -> list[CorrelationDeviation]:
    """Realized inter-trait correlations against the priors, worst gap first.

    Expected is Σ's correlation *plus* whatever μ co-varies across the pool, not Σ's
    alone — if two traits both drift with age, the demographic mix induces extra
    correlation between them that a correct sampler will show.
    """
    if len(personas) < 2:
        raise ValueError("cannot audit a pool of fewer than 2 personas")
    expected = _to_correlation(expected_moments(personas)[1])
    realized = np.corrcoef(_scores(personas).T)
    deviations = [
        CorrelationDeviation(
            trait_a=_TRAITS[i],
            trait_b=_TRAITS[j],
            expected=float(expected[i][j]),
            realized=float(realized[i][j]),
        )
        for i in range(len(_TRAITS))
        for j in range(i + 1, len(_TRAITS))
    ]
    return sorted(deviations, key=lambda d: abs(d.realized - d.expected), reverse=True)


def worst_deviation(
    marginals: list[MarginalDeviation], moments: list[MomentComparison]
) -> tuple[str, float]:
    """The largest |z| across both panels, and what it was.

    Takes the computed panels rather than the pool, so the caller that already has
    them does not pay to derive them a second time. Reported next to how many
    comparisons produced it, never as a verdict: across ~30 z-scores a healthy pool
    exceeds 2 more often than not, so the count is what makes the number readable.
    """
    candidates = [(f"{d.country} {d.dimension}/{d.category}", d.z) for d in marginals]
    for comparison in moments:
        candidates.append((f"{comparison.trait} mean", comparison.mean_z))
        candidates.append((f"{comparison.trait} sd", comparison.sd_z))
    return max(candidates, key=lambda pair: abs(pair[1]))


def format_report(personas: list[Persona]) -> str:
    tables = {
        country.value: load_joint(country)
        for country in Locale
        if any(p.country is country for p in personas)
    }
    counts: dict[str, int] = defaultdict(int)
    for persona in personas:
        counts[persona.country.value] += 1

    marginals = demographic_deviations(personas, tables)
    moments = bigfive_comparisons(personas)
    label, z = worst_deviation(marginals, moments)
    lines = [
        "=== Pool overview ===",
        f"{len(personas)} personas | "
        + ", ".join(f"{c} {counts[c]}" for c in sorted(counts)),
        f"worst of {len(marginals) + 2 * len(moments)} comparisons: "
        f"{label}, z = {z:+.2f}",
        "",
        "Demographics — realized vs. each country's own joint table, in standard errors:",
        f"  {'country  category':<30}{'target':>9}{'realized':>10}{'z':>8}",
    ]
    for deviation in marginals:
        row = f"{deviation.country}  {deviation.dimension}/{deviation.category}"
        lines.append(
            f"  {row:<30}{deviation.target:>9.3f}{deviation.realized:>10.3f}"
            f"{deviation.z:>8.2f}"
        )

    lines += [
        "",
        "Big Five — realized vs. priors conditioned on the pool's age/gender mix:",
        f"  {'trait':<20}{'E[mean]':>9}{'mean':>8}{'z':>7}{'E[sd]':>8}{'sd':>7}{'z':>7}",
    ]
    for comparison in moments:
        lines.append(
            f"  {comparison.trait:<20}{comparison.expected_mean:>9.3f}"
            f"{comparison.realized_mean:>8.3f}{comparison.mean_z:>7.2f}"
            f"{comparison.expected_sd:>8.3f}{comparison.realized_sd:>7.3f}"
            f"{comparison.sd_z:>7.2f}"
        )

    lines += ["", "Correlations — worst three gaps against the priors:"]
    for deviation in correlation_deviations(personas)[:3]:
        pair = f"{deviation.trait_a[:4]}/{deviation.trait_b[:4]}"
        lines.append(
            f"  {pair:<20}expected {deviation.expected:+.3f}   "
            f"realized {deviation.realized:+.3f}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the persisted persona pool.")
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="also render this many personas, for eyeballing individuals",
    )
    args = parser.parse_args()

    with psycopg.connect(settings.database_url) as conn:
        personas = load_pool(conn)
    if not personas:
        raise SystemExit("the pool is empty; run python -m app.seed first.")

    print(format_report(personas))
    # Spread across the pool rather than taking a prefix: ids sort by country, so
    # the first N are all from whichever country sorts first. Seeded so a browse is
    # repeatable when someone asks what you were looking at.
    rng = np.random.default_rng(0)
    for index in sorted(rng.permutation(len(personas))[: args.sample]):
        persona = personas[index]
        print(f"\n--- {persona.id}\n{render_persona_prompt(persona)}")


if __name__ == "__main__":
    main()
