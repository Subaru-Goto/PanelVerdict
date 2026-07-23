"""Stage 1 — build a country's demographic joint from the OECD SDMX API.

One keyless API, queried by country code. `age × gender × education` come as
direct OECD cross-tabs (education native ISCED-2011); income attaches as an
imputed marginal (declared). Design: issues/006b.
"""

import csv
import io
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.sampler import JointCell
from app.schemas import EducationLevel, Locale


class BuildResult(BaseModel):
    """A country's built joint plus the fidelity it was built at."""

    country: Locale
    rows: list[JointCell]
    income_marginal: list[float]  # realized, population-weighted quintile shares
    imputations: list[str]


# OECD reports attainment on ISCED-2011 already; these three aggregates are
# exactly our collapse (below-secondary / secondary / tertiary).
_ISCED_TO_EDUCATION = {
    "ISCED11A_0T2": EducationLevel.BELOW_SECONDARY,
    "ISCED11A_3_4": EducationLevel.SECONDARY,
    "ISCED11A_5T8": EducationLevel.TERTIARY,
}
_EDUCATION_ISCED = tuple(_ISCED_TO_EDUCATION)

_REF_AREA: dict[Locale, str] = {Locale.US: "USA", Locale.JP: "JPN", Locale.DE: "DEU"}

_SDMX_BASE = "https://sdmx.oecd.org/public/rest/data"
_POP_FLOW = "OECD.ELS.SAE,DSD_POPULATION@DF_POP_HIST"
_EDU_FLOW = "OECD.EDU.IMEP,DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA"
_POP_AGES = (
    "Y15T19+Y20T24+Y25T29+Y30T34+Y35T39+Y40T44+Y45T49+Y50T54"
    "+Y55T59+Y60T64+Y65T69+Y70T74+Y75T79+Y80T84+Y_GE85"
)
_EDU_AGES = "Y25T34+Y35T44+Y45T54+Y55T64"
_EDU_ATTAIN = "ISCED11A_0T2+ISCED11A_3_4+ISCED11A_5T8"

_IMPUTATIONS = [
    "education below 25 and 65+ borrow the nearest observed band (25-34 / 55-64)",
    "18-19 taken as 2/5 of the 15-19 population band",
    "income quintile conditioned on education (fixed prior), then raked to a "
    "uniform 20% marginal",
]

# High-completion peers whose below/secondary split stands in when a country
# reports only tertiary (e.g. JP). Chosen for similarity, not averaged blindly.
_SPLIT_PEERS: tuple[Locale, ...] = (Locale.US, Locale.DE)

# P(income quintile | education): a fixed, monotone prior with spread — income
# is grounded on education (the strongest predictor), but each row keeps mass
# across quintiles so educated-poor / uneducated-rich personas survive. Declared
# imputed; swap for per-country OECD earnings behind this table if drift warrants.
_INCOME_SPLIT: dict[EducationLevel, tuple[float, float, float, float, float]] = {
    EducationLevel.BELOW_SECONDARY: (0.35, 0.28, 0.20, 0.12, 0.05),
    EducationLevel.SECONDARY: (0.20, 0.22, 0.22, 0.20, 0.16),
    EducationLevel.TERTIARY: (0.08, 0.14, 0.20, 0.28, 0.30),
}


def _ref_area(country: Locale) -> str:
    return _REF_AREA[country]


def _pop_url(country: Locale) -> str:
    key = f"{_ref_area(country)}.POP.PS.M+F.{_POP_AGES}.H"
    return f"{_SDMX_BASE}/{_POP_FLOW}/{key}?lastNObservations=1"


def _edu_url(country: Locale) -> str:
    key = f"{_ref_area(country)}.M+F.{_EDU_AGES}.{_EDU_ATTAIN}..........OBS..."
    return f"{_SDMX_BASE}/{_EDU_FLOW}/{key}?lastNObservations=1"


def parse_sdmx_csv(text: str, dims: tuple[str, ...]) -> pd.DataFrame:
    """Read an SDMX-CSV response into `[*dims, value]`, one row per observation.

    Stays format-dumb: it only knows the SDMX-CSV convention of one column per
    dimension plus an OBS_VALUE column. Rows with no observation (empty
    OBS_VALUE, e.g. JP's missing split) are dropped, not errored.
    """
    raw = pd.read_csv(io.StringIO(text))
    kept = raw[raw["OBS_VALUE"].notna()]
    return (
        kept[[*dims, "OBS_VALUE"]]
        .rename(columns={"OBS_VALUE": "value"})
        .reset_index(drop=True)
    )


def _fetch_population(country: Locale, fetch: Callable[[str], str]) -> pd.DataFrame:
    """Population as `[age (5-year group), sex, count]`."""
    df = parse_sdmx_csv(fetch(_pop_url(country)), ("AGE", "SEX"))
    return df.rename(columns={"AGE": "age", "SEX": "sex", "value": "count"})


def _fetch_education(country: Locale, fetch: Callable[[str], str]) -> pd.DataFrame:
    """Education as `[age (OECD band), sex, isced, share]` (percent → share)."""
    df = parse_sdmx_csv(fetch(_edu_url(country)), ("AGE", "SEX", "ATTAINMENT_LEV"))
    df = df.rename(
        columns={"AGE": "age", "SEX": "sex", "ATTAINMENT_LEV": "isced", "value": "share"}
    )
    return df.assign(share=df["share"] / 100)


def _sex_to_gender(code: str) -> str:
    return {"F": "female", "M": "male"}[code]


def _isced_to_education(code: str) -> EducationLevel:
    return _ISCED_TO_EDUCATION[code]


def _low_age(group: str) -> int:
    """Lower bound of an OECD 5-year age group id ("Y25T29" -> 25, "Y_GE85" -> 85)."""
    body = group[1:]
    if body.startswith("_GE"):
        return int(body[3:])
    return int(body.split("T")[0])


def _dl_band_for_5yr(group: str) -> str:
    """Map a 5-year population group to its D&L band.

    Y15T19 lands in 18-19 (the only band above our 18 floor it touches); its
    below-floor fraction is dropped when weighting. Groups from 20 up fall in
    one decade band by their lower bound; 80+ is the open top band.
    """
    low = _low_age(group)
    if low < 20:
        return "18-19"
    if low >= 80:
        return "80+"
    start = (low // 10) * 10
    return f"{start}-{start + 9}"


def _edu_band_for_5yr(group: str) -> str:
    """Map a 5-year population group to the education band supplying its P(edu|·).

    Education is observed only for 25-64. Below 25 and 65+ have no data, so they
    borrow the nearest observed band (Y25T34 / Y55T64) — a better prior than a
    pooled mean since attainment is age-ordered. Declared imputed by the caller.
    """
    low = _low_age(group)
    if low < 25:
        return "Y25T34"
    if low >= 65:
        return "Y55T64"
    start = 25 + ((low - 25) // 10) * 10
    return f"Y{start}T{start + 9}"


def _floor_fraction(group: str) -> float:
    """Share of a 5-year group at or above the 18 age floor.

    Only Y15T19 straddles it: of ages 15-19, just 18-19 count, so 2/5. Every
    other group is wholly above 18.
    """
    return 0.4 if group == "Y15T19" else 1.0


def _education_is_incomplete(education: pd.DataFrame) -> bool:
    """True if any age×sex cell is missing one of the three attainment levels.

    Country-agnostic: it detects a gap of any shape (e.g. JP reports only
    tertiary), not a specific missing level.
    """
    per_cell = education.groupby(["age", "sex"])["isced"].nunique()
    return bool((per_cell < len(_EDUCATION_ISCED)).any())


def _complete_education_from_peers(
    education: pd.DataFrame, peers: list[pd.DataFrame]
) -> pd.DataFrame:
    """Fill whichever attainment levels a country omits, from peers.

    Works for any gap shape, not just JP's tertiary-only: per age×sex, the
    unreported mass (1 - sum of reported) is spread across the missing levels in
    proportion to the peers' mean shares of those same levels, so a similar peer
    group carries over its structure (and its age gradient). Reported levels stay
    exact. Declared imputed by the caller.
    """
    stacked = pd.concat(peers)
    peer_sum = stacked.groupby(["age", "sex", "isced"])["share"].sum()
    peer_count = stacked.groupby(["age", "sex", "isced"])["share"].size()
    additions = []
    for (age, sex), cell in education.groupby(["age", "sex"]):
        missing = [i for i in _EDUCATION_ISCED if i not in set(cell["isced"])]
        if not missing:
            continue
        for isced in missing:
            # every peer must report the level, else the peer set is inadequate
            # for this cell — fail loud rather than average over the subset.
            if peer_count.get((age, sex, isced), 0) < len(peers):
                raise ValueError(
                    f"a peer lacks {isced} at {(age, sex)}; it cannot supply the "
                    "split — choose peers that report every level"
                )
        means = {i: peer_sum[(age, sex, i)] / len(peers) for i in missing}
        missing_mass = 1.0 - cell["share"].sum()
        total = sum(means.values())
        for isced, mean_share in means.items():
            additions.append(
                {
                    "age": age,
                    "sex": sex,
                    "isced": isced,
                    "share": missing_mass * mean_share / total,
                }
            )
    return pd.concat([education, pd.DataFrame(additions)], ignore_index=True)


def combine(population: pd.DataFrame, education: pd.DataFrame) -> pd.DataFrame:
    """Cross population with education shares into an age×gender×education joint.

    Each 5-year population group takes its containing/nearest education band's
    shares, weighted by its (floor-adjusted) population; groups rolling up to the
    same D&L band blend together. Returns `[age_band, gender, education, weight]`.
    """
    pop = population.assign(
        edu_band=lambda d: d["age"].map(_edu_band_for_5yr),
        age_band=lambda d: d["age"].map(_dl_band_for_5yr),
        gender=lambda d: d["sex"].map(_sex_to_gender),
        floored=lambda d: d["count"] * d["age"].map(_floor_fraction),
    )
    merged = pop.merge(
        education.rename(columns={"age": "edu_band"}), on=["edu_band", "sex"]
    )
    merged = merged.assign(
        weight=merged["floored"] * merged["share"],
        # store the enum's string value: pandas coerces a str-Enum column to str
        # dtype anyway, and JointCell re-parses the string back to EducationLevel.
        education=merged["isced"].map(lambda c: _isced_to_education(c).value),
    )
    return (
        merged.groupby(["age_band", "gender", "education"])["weight"]
        .sum()
        .reset_index()
    )


def attach_income(combined: pd.DataFrame) -> pd.DataFrame:
    """Expand each age×gender×education cell into five income-quintile cells.

    The cell's weight is split across quintiles by `_INCOME_SPLIT[education]`,
    so mass is conserved and income skews with education.
    """
    split = pd.DataFrame(
        [
            (edu.value, quintile, share)
            for edu, shares in _INCOME_SPLIT.items()
            for quintile, share in enumerate(shares, start=1)
        ],
        columns=["education", "income_quintile", "split"],
    )
    merged = combined.merge(split, on="education")
    return merged.assign(weight=merged["weight"] * merged["split"]).drop(
        columns="split"
    )


def _rake_income(joint: pd.DataFrame) -> pd.DataFrame:
    """Rake the income split so quintiles are a true 20% each of the population.

    The fixed prior leaves the population-weighted quintile marginal off 20%
    (worse for high-tertiary countries). IPF reconciles two constraints — each
    age×gender×education cell keeps its real total, and every quintile sums to
    20% overall — adjusting only the within-cell split. It preserves the
    education→income association (odds ratios), so tertiary still skews high.
    """
    cells = ["age_band", "gender", "education"]
    table = joint.pivot_table(index=cells, columns="income_quintile", values="weight")
    matrix = table.to_numpy(copy=True)  # rows = cells, columns = quintiles

    target_quintile_mass = matrix.sum() / matrix.shape[1]
    cell_total = matrix.sum(axis=1, keepdims=True)  # real per-cell totals, preserved
    for _ in range(100):
        matrix *= target_quintile_mass / matrix.sum(axis=0, keepdims=True)  # columns
        matrix *= cell_total / matrix.sum(axis=1, keepdims=True)  # rows
        if np.abs(matrix.sum(axis=0) - target_quintile_mass).max() < 1e-9:
            break

    table.iloc[:, :] = matrix
    return table.reset_index().melt(
        id_vars=cells, var_name="income_quintile", value_name="weight"
    )


def build_oecd(country: Locale, *, fetch: Callable[[str], str]) -> BuildResult:
    """Build a country's joint from the OECD API via an injected `fetch`.

    `fetch(url) -> csv text` is injected so the orchestration is unit-testable
    without network. A country reporting only part of the attainment split has it
    completed from peers before combining.
    """
    population = _fetch_population(country, fetch)
    education = _fetch_education(country, fetch)
    imputations = list(_IMPUTATIONS)
    if _education_is_incomplete(education):
        peers = [p for p in _SPLIT_PEERS if p != country]
        education = _complete_education_from_peers(
            education, [_fetch_education(p, fetch) for p in peers]
        )
        names = ", ".join(p.value for p in peers)
        imputations.append(f"missing attainment level(s) completed from peers ({names})")

    joint = _rake_income(attach_income(combine(population, education)))
    joint = joint[joint["weight"] > 0]
    rows = [
        JointCell(
            age_band=row.age_band,
            gender=row.gender,
            education=row.education,
            income_quintile=int(row.income_quintile),
            weight=float(row.weight),
        )
        for row in joint.itertuples()
    ]
    marginal = joint.groupby("income_quintile")["weight"].sum()
    return BuildResult(
        country=country,
        rows=rows,
        income_marginal=(marginal / marginal.sum()).tolist(),
        imputations=imputations,
    )


_JOINT_COLUMNS = ["age_band", "gender", "education", "income_quintile", "weight"]


def write_joint(result: BuildResult, dest_dir: Path) -> None:
    """Write the joint CSV (what the sampler reads) plus a fidelity sidecar.

    The CSV columns mirror `JointCell` so `load_joint` reconstructs the cells
    verbatim; the `.meta.json` carries the fidelity the CSV can't (realized
    income marginal, declared imputations, source).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = result.country.value.lower()
    with (dest_dir / f"{stem}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_JOINT_COLUMNS)
        writer.writeheader()
        for cell in result.rows:
            writer.writerow(
                {
                    "age_band": cell.age_band,
                    "gender": cell.gender,
                    "education": cell.education.value,
                    "income_quintile": cell.income_quintile,
                    "weight": cell.weight,
                }
            )
    meta = {
        "country": result.country.value,
        "source": [_POP_FLOW, _EDU_FLOW],
        "income_marginal": result.income_marginal,
        "imputations": result.imputations,
    }
    (dest_dir / f"{stem}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def _http_fetch(url: str) -> str:
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.sdmx.data+csv; version=2.0",
            "User-Agent": "Mozilla/5.0 (panelverdict pipeline)",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode()


if __name__ == "__main__":
    import sys

    country = Locale(sys.argv[1])
    dest = Path(__file__).parents[1] / "app" / "data" / "joint"
    result = build_oecd(country, fetch=_http_fetch)
    write_joint(result, dest)
    print(
        f"wrote {country.value}: {len(result.rows)} rows; "
        f"income_marginal={[round(x, 3) for x in result.income_marginal]}"
    )
