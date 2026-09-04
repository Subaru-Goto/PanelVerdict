from pathlib import Path
from typing import get_args

from app.schemas import TraitLevel, TraitName
from app.splits import _AGE_BANDS, splits_by_variant
from tests.factories import make_panel_vote


def _voters(count: int, *, chosen: str, level: TraitLevel, start: int = 0):
    """`count` panelists at one conscientiousness level, all voting the same way."""
    return [
        make_panel_vote(
            f"p{start + index}",
            chosen=chosen,
            traits={
                "openness": TraitLevel.MEDIUM,
                "conscientiousness": level,
                "extraversion": TraitLevel.MEDIUM,
                "agreeableness": TraitLevel.MEDIUM,
                "neuroticism": TraitLevel.MEDIUM,
            },
        )
        for index in range(count)
    ]


def test_a_level_that_clears_the_report_s_bar_is_called_for_the_variant_it_chose():
    """27 of 38 is the smallest split a 38-vote cell can call decisive (measured
    against `stopping_decision`, docs in 041/#139), so this cell is the boundary
    case in the direction that must be named."""
    votes = [
        *_voters(27, chosen="b", level=TraitLevel.HIGH),
        *_voters(11, chosen="a", level=TraitLevel.HIGH, start=27),
    ]

    splits = splits_by_variant(votes)

    conscientiousness = next(
        split for split in splits.dimensions if split.dimension == "conscientiousness"
    )
    (high,) = [row for row in conscientiousness.rows if row.level == "high"]
    assert high.votes == 38
    assert high.verdict == "decisive"
    assert high.share_preferring_b is not None and high.share_preferring_b > 0.5


def test_age_is_split_by_the_band_it_was_drawn_from_not_the_concrete_age():
    """A concrete age is resolved uniformly inside its band at sample time
    (`pool_overview.age_band_of`), so the band is the only level a comparison
    can honestly be made at."""
    votes = [
        make_panel_vote("p0", chosen="b", age=22),
        make_panel_vote("p1", chosen="a", age=29),
        make_panel_vote("p2", chosen="b", age=34),
    ]

    splits = splits_by_variant(votes)

    age = next(split for split in splits.dimensions if split.dimension == "age_band")
    assert [(row.level, row.votes) for row in age.rows] == [
        ("20-29", 2),
        ("30-39", 1),
    ]


def test_every_dimension_the_voter_carries_is_crossed_with_the_variant():
    votes = [make_panel_vote("p0", chosen="b"), make_panel_vote("p1", chosen="a")]

    named = {split.dimension for split in splits_by_variant(votes).dimensions}

    assert named == {
        *get_args(TraitName),
        "age_band",
        "country",
        "gender",
        "education",
        "income_band",
    }


def test_the_age_bands_are_the_ones_the_pool_was_sampled_at():
    """`_AGE_BANDS` is a copy, so it can drift. The joint tables are the source:
    a band added or renamed there fails here rather than silently regrouping
    what a customer is shown. Membership only — the tables are not written in
    age order, and the order here is the one a reader is shown."""
    tables = sorted(Path("app/data/joint").glob("*.csv"))
    assert tables, "no joint tables found — the guard would pass on nothing"
    for table in tables:
        rows = table.read_text().splitlines()[1:]
        assert {row.split(",")[0] for row in rows if row} == set(_AGE_BANDS), table.name


def test_the_age_bands_read_youngest_first():
    """The render order, which the tables do not carry."""
    floors = [int(band.rstrip("+").split("-")[0]) for band in _AGE_BANDS]
    assert floors == sorted(floors)


def test_a_cell_too_thin_to_settle_anything_says_so_and_says_how_thin():
    """The case the ticket is named for: seven votes, and a share that must not
    be read as a finding. The sentence carries the votes and the gap this many
    could have called (22.5 points at 38, 38.9 at 7 — measured 2026-09-04), so
    the null is readable rather than merely absent."""
    votes = [
        *_voters(4, chosen="b", level=TraitLevel.VERY_HIGH),
        *_voters(3, chosen="a", level=TraitLevel.VERY_HIGH, start=4),
    ]

    (row,) = [
        row
        for split in splits_by_variant(votes).dimensions
        if split.dimension == "conscientiousness"
        for row in split.rows
    ]

    assert row.verdict == "undecided"
    assert row.too_few is not None
    assert "7 votes" in row.too_few


def test_a_wide_panel_that_merely_straddles_the_line_is_not_called_too_few():
    """232 of 400 is undecided with a 9.6-point interval, inside the band's own
    14 (measured 2026-09-04): the lean is measured perfectly well, it just sits
    across the line the band draws. Saying "too few" there would be false."""
    votes = [
        *_voters(232, chosen="b", level=TraitLevel.LOW),
        *_voters(168, chosen="a", level=TraitLevel.LOW, start=232),
    ]

    (row,) = [
        row
        for split in splits_by_variant(votes).dimensions
        if split.dimension == "conscientiousness"
        for row in split.rows
    ]

    assert row.verdict == "undecided"
    assert row.too_few is None


def test_every_trait_split_carries_the_demographic_it_is_entangled_with():
    """Traits are drawn from `MVN(mu(age band, gender), Sigma)`, so a trait level
    is partly a demographic by construction and a split on it can be an age or
    gender split wearing a personality name. Each row says which, and cites the
    record that makes it true."""
    votes = [make_panel_vote("p0", chosen="b"), make_panel_vote("p1", chosen="a")]

    splits = splits_by_variant(votes)
    traits = {
        split.dimension: split
        for split in splits.dimensions
        if split.dimension in get_args(TraitName)
    }

    assert set(traits) == set(get_args(TraitName))
    for trait, split in traits.items():
        assert split.demographic_confound is not None, trait
        assert "persona-seed-data" in split.demographic_confound, trait
    assert "age" in traits["conscientiousness"].demographic_confound
    assert "gender" in traits["neuroticism"].demographic_confound


def test_a_demographic_split_claims_no_confound_of_its_own():
    """Country, gender, education, income and age band are sampled from the joint
    table directly — nothing is derived from anything, so there is nothing to
    warn about and a warning would only teach the analyst to discount them."""
    votes = [make_panel_vote("p0", chosen="b"), make_panel_vote("p1", chosen="a")]

    for split in splits_by_variant(votes).dimensions:
        if split.dimension not in get_args(TraitName):
            assert split.demographic_confound is None, split.dimension


def _at(splits, dimension, level):
    (row,) = [
        row
        for split in splits.dimensions
        if split.dimension == dimension
        for row in split.rows
        if row.level == level
    ]
    return row


def test_a_lone_decisive_level_says_no_neighbour_agrees():
    """44 cells are read at once, so a single decisive row is weak evidence: with
    no effect at all, 39% of simulated reports carry one (300 reports,
    docs/research/vote-split-noise.md). An isolated call is the shape those take
    — the openness row in that record contradicted the level next to it."""
    votes = [
        *_voters(30, chosen="b", level=TraitLevel.VERY_HIGH),
        *_voters(2, chosen="a", level=TraitLevel.VERY_HIGH, start=30),
        *_voters(40, chosen="a", level=TraitLevel.HIGH, start=32),
        *_voters(40, chosen="b", level=TraitLevel.HIGH, start=72),
    ]

    splits = splits_by_variant(votes)

    very_high = _at(splits, "conscientiousness", "very_high")
    assert very_high.verdict == "decisive"
    assert very_high.isolated is not None
    assert "neighbour" in very_high.isolated


def test_two_neighbouring_levels_that_agree_are_a_pattern_not_an_isolated_call():
    """Adjacent and in the same direction: the shape a real effect takes, and the
    one a raised bar cannot tell from noise without also cutting true rows (the
    70-79 and 80+ bands in the same record)."""
    votes = [
        *_voters(30, chosen="b", level=TraitLevel.VERY_HIGH),
        *_voters(2, chosen="a", level=TraitLevel.VERY_HIGH, start=30),
        *_voters(30, chosen="b", level=TraitLevel.HIGH, start=32),
        *_voters(2, chosen="a", level=TraitLevel.HIGH, start=62),
    ]

    splits = splits_by_variant(votes)

    for level in ("very_high", "high"):
        row = _at(splits, "conscientiousness", level)
        assert row.verdict == "decisive", level
        assert row.isolated is None, level


def test_a_dimension_with_no_order_makes_no_claim_about_neighbours():
    """Country and gender have no adjacency to read, so silence is the honest
    answer — the standing note on the block covers them instead."""
    votes = [
        *[make_panel_vote(f"f{i}", chosen="b", gender="female") for i in range(30)],
        *[make_panel_vote(f"m{i}", chosen="a", gender="male") for i in range(30)],
    ]

    splits = splits_by_variant(votes)

    for dimension in ("gender", "country"):
        for row in next(
            s for s in splits.dimensions if s.dimension == dimension
        ).rows:
            assert row.isolated is None, dimension


def test_the_block_says_how_often_a_lone_call_is_noise():
    votes = [make_panel_vote("p0", chosen="b"), make_panel_vote("p1", chosen="a")]

    note = splits_by_variant(votes).reading_note

    assert "two of five" in note or "39" in note
    assert "vote-split-noise" in note


def test_the_note_counts_the_readings_this_block_actually_took():
    """The count is the substance of the caveat, so it cannot be a fixed number:
    a targeted panel takes fewer readings than an untargeted one, and claiming
    44 either way would misstate the evidence in both directions."""
    votes = [make_panel_vote("p0", chosen="b"), make_panel_vote("p1", chosen="a")]

    splits = splits_by_variant(votes)
    readings = sum(len(split.rows) for split in splits.dimensions)

    assert f"{readings} readings" in splits.reading_note
    assert readings < 44
