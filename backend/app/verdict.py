from dataclasses import dataclass

from scipy import optimize, stats

from app.schemas import Verdict, VoteRecord


@dataclass(frozen=True)
class Posterior:
    """How far the panel leans toward variant B, and how sure that lean is.

    `p` is the share of the panel preferring B over A. Which variant is the
    reference is a convention — A's share is `1 - p`.

    Two fields read alike and answer different questions:

    - `share_preferring_b` is E[p]: *about 62% of the panel prefer B*.
    - `probability_majority_prefers_b` is P(p > 0.5): *we are 97% sure more than
      half of them do*.

    Neither is a click-through rate. Real readers mostly see one variant and never
    make the comparison the panel was asked to make.
    """

    preferring_b: int
    total: int
    share_preferring_b: float
    probability_majority_prefers_b: float
    interval: tuple[float, float]


def _highest_density_interval(a: float, b: float, mass: float) -> tuple[float, float]:
    """The shortest interval of `mass` posterior probability.

    Equivalently the interval no point outside which is more plausible than a point
    inside — which is what makes it the right thing to compare against a ROPE, and
    what separates it from the equal-tailed interval on a skewed posterior.
    """
    dist = stats.beta(a, b)
    if a == 1 and b == 1:
        # Flat: every interval of the right mass is a highest-density one, so the
        # symmetric choice is simply the least surprising.
        return float(dist.ppf((1 - mass) / 2)), float(dist.ppf((1 + mass) / 2))
    # A unanimous panel leaves the density monotone, and the shortest interval then
    # runs to the boundary instead of sitting inside it.
    if a <= 1:
        return 0.0, float(dist.ppf(mass))
    if b <= 1:
        return float(dist.ppf(1 - mass)), 1.0

    def width(lower_tail: float) -> float:
        return float(dist.ppf(lower_tail + mass) - dist.ppf(lower_tail))

    lower_tail = optimize.minimize_scalar(
        width, bounds=(0.0, 1.0 - mass), method="bounded"
    ).x
    return float(dist.ppf(lower_tail)), float(dist.ppf(lower_tail + mass))


def posterior(
    *, preferring_b: int, total: int, credible_mass: float = 0.95
) -> Posterior:
    """Beta-Binomial posterior over p, the share of the panel that prefers B.

    A flat Beta(1, 1) prior makes this conjugate: the posterior is
    Beta(1 + k, 1 + n - k), exact and closed-form, which is why no sampler appears
    here and why a batch update is just an addition (009).

    An empty panel is not an error — it returns the prior, which is the honest
    answer to "what do we know before anyone has voted".
    """
    if total < 0:
        raise ValueError(f"total must not be negative, got {total}")
    if not 0 <= preferring_b <= total:
        raise ValueError(f"{preferring_b} of {total} votes is not a possible split")
    if not 0 < credible_mass < 1:
        raise ValueError(f"credible_mass must lie in (0, 1), got {credible_mass}")

    a, b = 1 + preferring_b, 1 + total - preferring_b
    return Posterior(
        preferring_b=preferring_b,
        total=total,
        # The Beta mean, not k/n: the prior pulls a small sample toward a tie, so
        # six of ten reads as 0.583 rather than 0.600.
        share_preferring_b=a / (a + b),
        probability_majority_prefers_b=float(stats.beta(a, b).sf(0.5)),
        interval=_highest_density_interval(a, b, credible_mass),
    )


def tally_votes(records: list[VoteRecord], variant_ids: list[str]) -> Verdict:
    """Count votes per variant.

    counts is zero-filled over variant_ids, so a variant with no votes still
    reports 0. On a tie, winner is the first tied variant in variant_ids order
    (an arbitrary tiebreak).
    """
    counts = {variant_id: 0 for variant_id in variant_ids}
    for record in records:
        counts[record.chosen_variant_id] += 1
    winner = max(counts, key=counts.get)
    return Verdict(counts=counts, total=len(records), winner=winner)
