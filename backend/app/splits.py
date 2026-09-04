"""Who preferred which variant, one dimension at a time.

Pure: votes in, the block out. No database and no model call, so the reading a
customer is shown can be tested without either (041/#139).

Every figure here comes from `verdict.py` unchanged — the same posterior, the
same `ROPE`, the same bar the report's own recommendation fires at. A subgroup
is just a smaller panel, so it needs no statistics of its own.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Literal, get_args

from pydantic import BaseModel

from app.pool_overview import age_band_of
from app.schemas import (
    EducationLevel,
    IncomeBand,
    PanelVote,
    RopeVerdict,
    TraitLevel,
    TraitName,
    VoterSummary,
)
from app.verdict import (
    CREDIBLE_MASS,
    ROPE,
    detectable_gap,
    panel_verdict,
    stopping_decision,
)

# A tenth of a preference point, finer than any sentence about a panel of a few
# hundred can carry. Three full doubles ride on every row, so rounding is worth
# 440 tokens of the 4,511 the block came to without it
# (docs/research/vote-split-noise.md).
_SHARE_PLACES = 3

# The dimensions a voter can be grouped by, as one closed type rather than bare
# strings: the same reasoning `_grouped` gives in analyst.py, that a mistyped
# dimension should be a type error here and not a silently empty group on the
# wire.
Dimension = (
    TraitName | Literal["age_band", "country", "gender", "education", "income_band"]
)

# The joint table's own bands (`app/data/joint/*.csv`, column `age_band`), which
# `test_splits.py` reads back to prove this copy has not drifted. Restated here
# rather than loaded because this module touches no files, and they are also the
# bands mu is a function of (`docs/research/persona-seed-data.md`), which is what
# makes the age comparison a fair check on a trait split rather than decoration.
_AGE_BANDS = (
    "18-19",
    "20-29",
    "30-39",
    "40-49",
    "50-59",
    "60-69",
    "70-79",
    "80+",
)


# Each trait is drawn from `MVN(mu(age band, gender), Sigma)`, so its level carries
# whatever demographic mu depends on. The strengths differ enough that one blanket
# warning would be wrong: over the eight bands the age main effect spans 0.89 z for
# conscientiousness and 0.14 for neuroticism, while the pooled gender d runs from
# -0.02 for openness to +0.45 for neuroticism (docs/research/persona-seed-data.md,
# from Donnellan & Lucas 2008). So each sentence names the demographic that actually
# dominates that trait, and the risk is misattribution rather than reversal: the
# levels partition the panel, so a majority in every level is a majority overall.
_CONFOUND: dict[Dimension, str] = {
    "openness": (
        "Openness falls with age in this pool by construction and barely differs "
        "by gender, so a split on it may be an age split "
        "(docs/research/persona-seed-data.md). Read the age_band rows first."
    ),
    "conscientiousness": (
        "Conscientiousness is the most age-dependent trait in this pool by "
        "construction — lowest in the youngest band, highest in middle age — so a "
        "split on it may be an age split (docs/research/persona-seed-data.md). "
        "Read the age_band rows first."
    ),
    "extraversion": (
        "Extraversion falls with age in this pool and runs a little higher in women, "
        "both by construction, so a split on it may be an age or gender split "
        "(docs/research/persona-seed-data.md). Read those rows first."
    ),
    "agreeableness": (
        "Agreeableness rises with age in this pool and runs higher in women, both by "
        "construction and to a similar degree, so a split on it may be either "
        "(docs/research/persona-seed-data.md). Read the age_band and gender rows "
        "first."
    ),
    "neuroticism": (
        "Neuroticism is the most gender-dependent trait in this pool by construction "
        "and hardly moves with age, so a split on it may be a gender split "
        "(docs/research/persona-seed-data.md). Read the gender rows first."
    ),
}


# The dimensions whose levels have an order, and that order. Adjacency is only
# readable where one exists, and each of these is ordered by its own type rather
# than restated: a level added to any of them lands in the right place here.
_ORDERS: dict[Dimension, tuple[str, ...]] = {
    **{
        trait: tuple(level.value for level in TraitLevel)
        for trait in get_args(TraitName)
    },
    "age_band": _AGE_BANDS,
    "education": tuple(level.value for level in EducationLevel),
    "income_band": get_args(IncomeBand),
}


class SplitRow(BaseModel):
    """One level of one dimension, and what its votes did or did not settle."""

    level: str
    votes: int
    verdict: RopeVerdict
    share_preferring_b: float
    credible_interval: tuple[float, float]
    # The share travels welded to its interval rather than withheld: a seven-vote
    # cell arrives as [0.25, 0.85], which defeats the number without hiding it.
    # This sentence is the same warning in words the analyst can say, set on every
    # cell whose interval is wider than the band — called or not, since a thin
    # cell can clear the bar. A field the suite can hold, where obedience to a
    # prompt rule cannot be.
    too_few: str | None = None
    # Set on a decisive row no neighbouring level agrees with, where the
    # dimension has an order to read. See `_isolated_levels`.
    isolated: str | None = None


class DimensionSplit(BaseModel):
    """One dimension's levels, biggest group first."""

    dimension: Dimension
    rows: list[SplitRow]
    # Traits only. The demographics come off the joint table directly, so there is
    # nothing to warn about, and warning anyway would teach the analyst to
    # discount the rows its trait warnings tell it to check.
    demographic_confound: str | None = None


class VoteSplits(BaseModel):
    """The whole crosstab, with the band and the mass stated once.

    Once rather than per row: they are the same on every row, and the top-level
    verdict already carries them — forty copies would be forty copies of one fact.
    """

    rope: tuple[float, float]
    credible_mass: float
    # The half of every warning that does not change from cell to cell. Built
    # rather than fixed because the row count is the substance of the sentence,
    # and a targeted panel has fewer rows than an untargeted one.
    reading_note: str
    dimensions: list[DimensionSplit]


def _too_few(
    total: int, interval: tuple[float, float], band: float, *, called: bool
) -> str | None:
    """What a cell too coarse to carry a share says, or None if it is not.

    The test is the interval's width against the band, not the verdict: a cell
    whose reading is wider than the difference the band calls meaningful cannot
    support a share, whether or not it cleared the bar. That covers both halves
    of the ticket's Done-when clause. Keying off `undecided` instead let seven
    unanimous votes ship 0.889 with no warning at all, and would separately have
    called 232 of 400 "too few" when its interval is 10 points wide and merely
    straddles the band's edge.

    Short on purpose: forty-four of these ride on one payload, so the standing
    half of the warning is stated once on `VoteSplits.reading_note` and only what
    differs per cell is here. The long form was 1,760 tokens a run
    (docs/research/vote-split-noise.md).
    """
    low, high = interval
    if high - low <= band:
        return None
    gap = detectable_gap(total=total)
    if gap is None:
        # Never a called cell: `detectable_gap` returns None only at sizes where
        # no split at all is decisive, four votes and under.
        return f"{total} votes settled nothing, at any gap."
    if called:
        # A thin cell can still clear the bar — seven unanimous votes do — and
        # the ticket's Done-when clause is about exactly that case: the verdict
        # stands, but a share read off a 31-point interval is not a figure to act
        # on. Keying off `undecided` shipped 0.889 on seven votes with no warning.
        return (
            f"{total} votes: called, but nothing under a "
            f"{gap * 100:.0f}-point gap could have been settled here. Read the "
            "direction, not the share."
        )
    return f"{total} votes settled nothing; needed a {gap * 100:.0f}-point gap."


def _row(level: str, *, preferring_b: int, total: int) -> SplitRow:
    verdict = panel_verdict(preferring_b=preferring_b, total=total)
    # `stopping_decision` is the report's own bar — it returns None where the
    # report would make no call, which is `undecided` in the reader's words.
    called = stopping_decision(preferring_b=preferring_b, total=total)
    band_low, band_high = ROPE
    return SplitRow(
        level=level,
        votes=total,
        verdict=called or "undecided",
        share_preferring_b=round(verdict.share_preferring_b, _SHARE_PLACES),
        credible_interval=(
            round(verdict.credible_interval[0], _SHARE_PLACES),
            round(verdict.credible_interval[1], _SHARE_PLACES),
        ),
        too_few=_too_few(
            total,
            verdict.credible_interval,
            band_high - band_low,
            called=called is not None,
        ),
    )


_ISOLATED = (
    "No neighbouring level agrees. On its own this is weak: a lone call like it "
    "turns up in about two of five panels with no real effect "
    "(docs/research/vote-split-noise.md)."
)


def _isolated_levels(dimension: Dimension, rows: list[SplitRow]) -> set[str]:
    """The decisive levels no neighbouring level agrees with.

    Every level of every dimension is read at one bar, so a lone call is weak
    evidence: with no effect at all, 39% of simulated panels carry one, and
    agreement between adjacent levels is what tells a real one from noise.
    `docs/research/vote-split-noise.md` measures both sides and records why
    raising the per-cell bar was rejected instead.

    Ordinal dimensions only. Country and gender have no adjacency to read, so
    they get no claim either way and the block's standing note covers them.
    """
    order = _ORDERS.get(dimension)
    if order is None:
        return set()
    ranked = sorted(rows, key=lambda row: order.index(row.level))
    lone = set()
    for index, row in enumerate(ranked):
        if row.verdict != "decisive":
            continue
        neighbours = ranked[max(index - 1, 0) : index] + ranked[index + 1 : index + 2]
        # Same direction, not merely adjacent: `very_high` calling A next to
        # `high` leaning B is two rows contradicting each other, not a pattern.
        if not any(
            neighbour.verdict == "decisive"
            and (neighbour.share_preferring_b > 0.5) == (row.share_preferring_b > 0.5)
            for neighbour in neighbours
        ):
            lone.add(row.level)
    return lone


def _split(dimension: Dimension, tallies: dict[str, tuple[int, int]]) -> DimensionSplit:
    """Biggest group first, ties on the level's name — the ordering `_grouped`
    already uses, so a panel always renders identically."""
    rows = [
        _row(level, preferring_b=preferring_b, total=total)
        for level, (preferring_b, total) in sorted(
            tallies.items(), key=lambda pair: (-pair[1][1], pair[0])
        )
    ]
    # Adjacency can only be read once every level exists, so this is a second
    # pass — but the rows are rebuilt rather than mutated, the way
    # `_composition_of_voters` and `verdict.py` build theirs complete.
    lone = _isolated_levels(dimension, rows)
    return DimensionSplit(
        dimension=dimension,
        rows=[
            row.model_copy(update={"isolated": _ISOLATED}) if row.level in lone else row
            for row in rows
        ],
        demographic_confound=_CONFOUND.get(dimension),
    )


def levels_of(voter: VoterSummary) -> list[tuple[Dimension, str]]:
    """Every dimension this voter can be grouped by, as (dimension, level).

    Age is the one that needs converting: it arrives as a concrete number and is
    grouped at its band, since that is the resolution it was drawn at.
    """
    return [
        *((trait, voter.traits[trait].value) for trait in get_args(TraitName)),
        ("age_band", age_band_of(voter.age, _AGE_BANDS)),
        ("country", voter.country.value),
        ("gender", voter.gender),
        ("education", voter.education.value),
        ("income_band", voter.income_band),
    ]


def _reading_note(readings: int) -> str:
    """The standing half of every caveat in the block, said once.

    The row count is the substance, not decoration: these are that many readings
    taken at one bar, which is why a single decisive row is weak evidence.
    """
    return (
        "A row carrying too_few settled nothing: say so, and do not read its "
        "share as a finding. A trait split may be an age or gender split — see "
        f"each trait's demographic_confound. This block is {readings} readings at "
        "one bar, so a lone decisive row is weak on its own: about two of five "
        "panels with no real effect show one "
        "(docs/research/vote-split-noise.md). Levels agreeing with their "
        "neighbours are the finding; a row marked isolated is not."
    )


def splits_by_variant(votes: Sequence[PanelVote]) -> VoteSplits:
    """Each dimension of the voters crossed with the variant they chose."""
    tallies: dict[Dimension, dict[str, tuple[int, int]]] = defaultdict(
        lambda: defaultdict(lambda: (0, 0))
    )
    for vote in votes:
        chose_b = vote.chosen_variant_id == "b"
        for dimension, level in levels_of(vote.voter):
            preferring_b, total = tallies[dimension][level]
            tallies[dimension][level] = (preferring_b + chose_b, total + 1)

    dimensions = [_split(dimension, levels) for dimension, levels in tallies.items()]
    return VoteSplits(
        rope=ROPE,
        credible_mass=CREDIBLE_MASS,
        reading_note=_reading_note(sum(len(split.rows) for split in dimensions)),
        dimensions=dimensions,
    )
