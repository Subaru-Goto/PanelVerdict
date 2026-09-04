from dataclasses import asdict, dataclass

from scipy import optimize, stats

from app.schemas import (
    PanelVerdict,
    StopReason,
    PreferenceExposure,
    PreferenceProbability,
    RopeVerdict,
    VoteRecord,
    VoteTally,
)

# ±7 preference-share points around even: within it, a difference is too small to
# act on. Two reasons for the width, both measured in
# docs/research/adaptive-stopping.md: a ±3 band cannot contain
# the HDI until ~1,100 votes, so `practical_tie` would never have been reachable at
# an affordable panel size; and 7 points sits inside the panel's own 11-20% flip
# rate, so calling it a tie is honesty rather than laxity. It cannot be derived from
# the posterior — it encodes what difference is worth acting on, which is a domain
# judgment. Signed off 2026-07-27.
ROPE = (0.43, 0.57)

# The share of the posterior a call has to sit inside. One definition rather than
# the four identical literals that used to sit in the signatures below: 041/#139
# needed to name the bar without computing a throwaway verdict to read it off.
CREDIBLE_MASS = 0.95


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


def _checked_split(preferring_b: int, total: int) -> tuple[int, int]:
    """Validate a vote split and return the posterior's Beta parameters."""
    if total < 0:
        raise ValueError(f"total must not be negative, got {total}")
    if not 0 <= preferring_b <= total:
        raise ValueError(f"{preferring_b} of {total} votes is not a possible split")
    return 1 + preferring_b, 1 + total - preferring_b


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


@dataclass(frozen=True)
class PreferenceShortfall:
    """What each choice risks, in preference-share points, both ways.

    Reporting both directions is what lets a practical tie read as *"either
    headline risks under a tenth of a point"* rather than as an accusation against
    one of them.
    """

    shipping_a: float
    shipping_b: float


def expected_preference_shortfall(
    *, preferring_b: int, total: int
) -> PreferenceShortfall:
    """Average preference-share points a choice falls short of an even split by,
    weighted by the probability that it does.

    This is the **expected loss** of Bayesian decision theory, deliberately not
    named that. In a marketing report "loss" reads as money, and this measures
    neither money nor reader behaviour — only how the panel split.

    It answers what `probability_majority_prefers_b` cannot: not *how often* a
    choice would be wrong, but *how far* wrong, weighted by that likelihood. Two
    panels of near-equal confidence can differ several-fold here, because a small
    panel has fat tails — if it is wrong, it is wrong by more. That is why this is
    the sounder stopping signal, since early stopping lands precisely in the
    small-panel regime.

    Decomposes as `P(that choice is worse) x average shortfall in that branch`; the
    conditional magnitude alone is not reported because it has no likelihood
    attached and so compares to nothing.
    """
    a, b = _checked_split(preferring_b, total)
    # E[(0.5-p)+] = 0.5*F(0.5; a, b) - E[p]*F(0.5; a+1, b), and the mirror for the
    # other tail. Closed form in two Beta CDFs, so nothing is integrated at runtime.
    mean = a / (a + b)
    below = stats.beta(a, b).cdf(0.5)
    below_shifted = stats.beta(a + 1, b).cdf(0.5)
    shipping_b = 0.5 * below - mean * below_shifted
    shipping_a = mean * (1 - below_shifted) - 0.5 * (1 - below)
    return PreferenceShortfall(
        shipping_a=float(shipping_a), shipping_b=float(shipping_b)
    )


@dataclass(frozen=True)
class MeaningfulPreference:
    """How likely each variant is to be preferred by more than the band.

    Key `a` is about variant A, deliberately unlike `PreferenceShortfall`'s
    `shipping_*` keys — the differing key sets guard the units, which differ too:
    probability in 0-1 against preference-share points.
    """

    a: float
    b: float


def probability_meaningfully_preferred(
    *, preferring_b: int, total: int, rope: tuple[float, float] = ROPE
) -> MeaningfulPreference:
    """How probable it is that each variant wins by an amount worth acting on.

    The band's own question, answered as a probability instead of a bucket. A three-way
    label reads `undecided` for everything from a coin flip to a near-certainty — at
    65/100 it says `undecided` about something this puts near 0.95 — because comparing an
    interval to a band throws away where inside the interval the mass actually sits.

    Was `probability_worth_acting_on` with `shipping_*` keys, "named for what a
    reader does with it, not for the geometry". The reader decided otherwise:
    the reader-facing sentence became "Chance A is preferred", and the
    decision-named wire forced the frontend to cross `shipping_b` onto A's
    tile. Now the
    name follows the sentence: `a` is the mass below the band, where A leads.
    """
    # Not the file's usual `a, b` locals: here those names are the *variant* keys
    # being constructed, and the Beta parameters must not share them.
    alpha, beta = _checked_split(preferring_b, total)
    low, high = rope
    distribution = stats.beta(alpha, beta)
    return MeaningfulPreference(
        a=float(distribution.cdf(low)),
        b=float(1 - distribution.cdf(high)),
    )


def probability_practical_tie(
    *, preferring_b: int, total: int, rope: tuple[float, float] = ROPE
) -> float:
    """How probable it is that the difference is too small to act on either way.

    The positive finding the band exists for, and the one thing no interval-free
    posterior can assert: a narrow interval near even is not evidence of equivalence
    until something says how near counts.
    """
    a, b = _checked_split(preferring_b, total)
    low, high = rope
    distribution = stats.beta(a, b)
    return float(distribution.cdf(high) - distribution.cdf(low))


def stopping_decision(
    *,
    preferring_b: int,
    total: int,
    rope: tuple[float, float] = ROPE,
    credible_mass: float = CREDIBLE_MASS,
) -> StopReason | None:
    """Whether more votes would change what the report says — None means keep buying.

    The rule chosen over three agreeing labels: stop when the report would
    already make a call, at the report's own bar. `credible_mass` is the only
    threshold, so the run stops exactly when the render-time recommendation would
    fire — no second constant to source, and no gap where the run stops before the
    report would call it or keeps spending after it has.

    Both stops are answers. `decisive` in either direction, and `practical_tie` —
    the stop a label-agreement rule could never take, because the label fires on
    ~5.6% of genuinely tied splits and three in a row effectively never.
    """
    preferred = probability_meaningfully_preferred(
        preferring_b=preferring_b, total=total, rope=rope
    )
    if max(preferred.a, preferred.b) >= credible_mass:
        return "decisive"
    if (
        probability_practical_tie(preferring_b=preferring_b, total=total, rope=rope)
        >= credible_mass
    ):
        return "practical_tie"
    return None


def detectable_gap(
    *,
    total: int,
    rope: tuple[float, float] = ROPE,
    credible_mass: float = CREDIBLE_MASS,
) -> float | None:
    """The smallest preference gap a panel this size could call decisive, or None.

    What makes a small panel's null result readable. *"This panel could have detected any
    gap this wide and found none"* is a finding; `undecided` on its own is not, because it
    cannot be told apart from a panel that found genuine equivalence.

    Derived rather than configured: it follows from the panel size and the band, so
    storing it would be asserting a precision that was not bought. It exceeds the band's
    half-width at every size — a difference the band calls negligible stays negligible
    however much is spent — and it approaches that half-width only as the interval
    narrows, which costs the square of the improvement. The trend is what holds, not
    every step: the boundary moves in whole votes, so one more panelist can round the
    other way and widen it a little.

    Bisected because the verdict is monotone in the split: once the interval clears the
    band it stays clear, so the boundary can be found in log time rather than by walking
    every split.

    Reported as a **posterior** lean, not `k / n`, so that it can be read straight against
    `share_preferring_b` and the band — both of which live in that same shrunk space. The
    two differ by 2 points at the dev size, which is the size where this number matters
    most.
    """
    low, high = total // 2, total
    if _verdict_at(total, high, rope, credible_mass) != "decisive":
        return None
    while low + 1 < high:
        middle = (low + high) // 2
        if _verdict_at(total, middle, rope, credible_mass) == "decisive":
            high = middle
        else:
            low = middle
    a, b = _checked_split(high, total)
    return a / (a + b) - 0.5


def _verdict_at(
    total: int, preferring_b: int, rope: tuple[float, float], credible_mass: float
) -> RopeVerdict:
    a, b = _checked_split(preferring_b, total)
    return rope_verdict(_highest_density_interval(a, b, credible_mass), rope=rope)


def rope_verdict(
    interval: tuple[float, float], *, rope: tuple[float, float] = ROPE
) -> RopeVerdict:
    """Compare a credible interval against the region of practical equivalence.

    Not what a report carries — a verdict states the band as probabilities, since a label
    reads `undecided` from a coin flip all the way to a near-certainty. And no longer the
    stopping rule either, which now fires on the probabilities crossing
    `credible_mass` directly. What keeps this alive is `detectable_gap`, whose
    boundary is defined by this comparison going decisive.

    Three outcomes, and the third is the point of the method: `undecided` is a
    statement about the data, where `practical_tie` is a *positive* finding — the
    difference is credibly too small to matter, which "not significant" can never
    say. The band is closed: a share of exactly 0.57 is negligible by the band's
    own definition, so an interval touching the edge still has mass on negligible
    values and may not claim `decisive`.

    Assumes the interval is an HDI — for a skewed posterior the equal-tailed
    interval can include values less plausible than ones it excludes, which is
    exactly the property this comparison cannot tolerate.
    """
    lo, hi = interval
    rope_lo, rope_hi = rope
    if not (0 <= rope_lo < rope_hi <= 1):
        raise ValueError(f"not a band: {rope}")
    if lo > hi:
        raise ValueError(f"not an interval: {interval}")

    if hi < rope_lo or lo > rope_hi:
        return "decisive"
    if rope_lo <= lo and hi <= rope_hi:
        return "practical_tie"
    return "undecided"


def posterior(
    *, preferring_b: int, total: int, credible_mass: float = CREDIBLE_MASS
) -> Posterior:
    """Beta-Binomial posterior over p, the share of the panel that prefers B.

    A flat Beta(1, 1) prior makes this conjugate: the posterior is
    Beta(1 + k, 1 + n - k), exact and closed-form, which is why no sampler appears
    here, and why a batch update is just an addition.

    An empty panel is not an error — it returns the prior, which is the honest
    answer to "what do we know before anyone has voted".
    """
    if not 0 < credible_mass < 1:
        raise ValueError(f"credible_mass must lie in (0, 1), got {credible_mass}")
    a, b = _checked_split(preferring_b, total)
    return Posterior(
        preferring_b=preferring_b,
        total=total,
        # The Beta mean, not k/n: the prior pulls a small sample toward a tie, so
        # six of ten reads as 0.583 rather than 0.600.
        share_preferring_b=a / (a + b),
        probability_majority_prefers_b=float(stats.beta(a, b).sf(0.5)),
        interval=_highest_density_interval(a, b, credible_mass),
    )


def tally_votes(records: list[VoteRecord], variant_ids: list[str]) -> VoteTally:
    """Count votes per variant, descriptively.

    counts is zero-filled over variant_ids, so a variant with no votes still
    reports 0. No winner is derived: a count leader carries no uncertainty, and the
    tiebreak it used to need was arbitrary. `panel_verdict` decides.
    """
    counts = {variant_id: 0 for variant_id in variant_ids}
    for record in records:
        counts[record.chosen_variant_id] += 1
    return VoteTally(counts=counts, total=len(records))


def panel_verdict(
    *,
    preferring_b: int,
    total: int,
    rope: tuple[float, float] = ROPE,
    credible_mass: float = CREDIBLE_MASS,
) -> PanelVerdict:
    """Assemble the reportable verdict: posterior, the band's probabilities, and the band.

    The band travels with the verdict rather than being implied, because it is a
    product decision rather than a derived quantity: a verdict silent about which
    band produced it could be re-labelled later with nothing to notice.
    """
    summary = posterior(
        preferring_b=preferring_b, total=total, credible_mass=credible_mass
    )
    shortfall = expected_preference_shortfall(preferring_b=preferring_b, total=total)
    meaningfully_preferred = probability_meaningfully_preferred(
        preferring_b=preferring_b, total=total, rope=rope
    )
    return PanelVerdict(
        share_preferring_b=summary.share_preferring_b,
        probability_majority_prefers_b=summary.probability_majority_prefers_b,
        credible_interval=summary.interval,
        credible_mass=credible_mass,
        rope=rope,
        probability_meaningfully_preferred=PreferenceProbability(
            **asdict(meaningfully_preferred)
        ),
        probability_practical_tie=probability_practical_tie(
            preferring_b=preferring_b, total=total, rope=rope
        ),
        detectable_gap=detectable_gap(
            total=total, rope=rope, credible_mass=credible_mass
        ),
        expected_preference_shortfall=PreferenceExposure(**asdict(shortfall)),
    )
