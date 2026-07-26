import math

import pytest

from app.schemas import TraitLevel
from experiments.analysis import (
    control_share,
    flip_rate,
    gradient,
    noise_floor,
    position_bias,
)
from experiments.design import VoteRow

HIGH, LOW = "predicted_high", "predicted_low"


def row(**overrides) -> VoteRow:
    base = dict(
        arm="traits_5",
        trait="openness",
        level=TraitLevel.MEDIUM.value,
        persona_id="openness-medium",
        pair_id="openness",
        replicate=0,
        order=HIGH,
        chosen=HIGH,
        reason="",
    )
    return VoteRow(**(base | overrides))


def sweep_rows(
    shares: dict[TraitLevel, int], *, n: int, arm: str = "traits_5"
) -> list[VoteRow]:
    """n votes per level, `shares[level]` of them for predicted_high."""
    return [
        row(
            arm=arm,
            level=level.value,
            persona_id=f"openness-{level.value}",
            replicate=index,
            order=HIGH if index % 2 == 0 else LOW,
            chosen=HIGH if index < high else LOW,
        )
        for level, high in shares.items()
        for index in range(n)
    ]


class TestNoiseFloor:
    def test_identical_replicates_have_no_disagreement(self):
        rows = [row(replicate=index) for index in range(4)]
        assert noise_floor(rows) == 0.0

    def test_an_even_split_disagrees_at_the_chance_rate(self):
        """Two of four replicates flipped: 4 of the 6 unordered pairs differ."""
        rows = [
            row(replicate=index, chosen=HIGH if index < 2 else LOW)
            for index in range(4)
        ]
        assert noise_floor(rows) == pytest.approx(4 / 6)

    def test_cells_are_not_pooled_across_arms_or_orders(self):
        """A cell is one prompt run twice; different arms are different prompts."""
        rows = [
            row(arm="traits_5", replicate=0, chosen=HIGH),
            row(arm="traits_5", replicate=1, chosen=HIGH),
            row(arm="demographics", replicate=0, chosen=LOW),
            row(arm="demographics", replicate=1, chosen=LOW),
        ]
        assert noise_floor(rows) == 0.0

    def test_single_replicate_cells_contribute_nothing(self):
        assert noise_floor([row()]) == 0.0

    def test_the_control_pair_is_excluded(self):
        """It is authored to be undisputed, so pooling it drags the floor down."""
        rows = [
            row(pair_id="control", replicate=index, chosen=HIGH) for index in range(4)
        ] + [
            row(replicate=index, chosen=HIGH if index < 2 else LOW)
            for index in range(4)
        ]
        assert noise_floor(rows) == pytest.approx(4 / 6)


class TestFlipRate:
    def test_arms_that_agree_everywhere_do_not_flip(self):
        rows = sweep_rows({TraitLevel.MEDIUM: 2}, n=2) + sweep_rows(
            {TraitLevel.MEDIUM: 2}, n=2, arm="demographics"
        )
        assert flip_rate(rows, "demographics", "traits_5") == 0.0

    def test_flips_are_counted_per_matched_vote_not_per_margin(self):
        """The point of pairing: identical margins, every vote flipped."""
        rows = [
            row(arm="traits_5", replicate=0, chosen=HIGH),
            row(arm="traits_5", replicate=1, chosen=LOW),
            row(arm="demographics", replicate=0, chosen=LOW),
            row(arm="demographics", replicate=1, chosen=HIGH),
        ]
        assert flip_rate(rows, "demographics", "traits_5") == 1.0

    def test_unmatched_cells_are_rejected_rather_than_silently_dropped(self):
        rows = [
            row(arm="traits_5"),
            row(arm="demographics", persona_id="openness-high"),
        ]
        with pytest.raises(ValueError, match="do not line up"):
            flip_rate(rows, "demographics", "traits_5")

    def test_the_control_pair_cannot_dilute_the_flip_rate(self):
        rows = [
            row(arm="traits_5", chosen=HIGH),
            row(arm="demographics", chosen=LOW),
            row(arm="traits_5", pair_id="control", chosen=HIGH),
            row(arm="demographics", pair_id="control", chosen=HIGH),
        ]
        assert flip_rate(rows, "demographics", "traits_5") == 1.0

    def test_restricting_to_the_extremes_undilutes_the_granularity_comparison(self):
        """traits_3 and traits_5 render identically unless an extreme was drawn, so
        the middle levels can only ever contribute zero flips."""
        rows = [
            row(
                arm=arm,
                level=level.value,
                persona_id=f"openness-{level.value}",
                chosen=chosen,
            )
            for level in TraitLevel
            for arm, chosen in (
                ("traits_3", LOW),
                (
                    "traits_5",
                    HIGH
                    if level in (TraitLevel.VERY_LOW, TraitLevel.VERY_HIGH)
                    else LOW,
                ),
            )
        ]
        assert flip_rate(rows, "traits_3", "traits_5") == pytest.approx(2 / 5)
        assert (
            flip_rate(rows, "traits_3", "traits_5", levels=("very_low", "very_high"))
            == 1.0
        )


class TestGradient:
    def test_shares_are_reported_per_level_in_order(self):
        rows = sweep_rows(
            {
                TraitLevel.VERY_LOW: 0,
                TraitLevel.LOW: 1,
                TraitLevel.MEDIUM: 2,
                TraitLevel.HIGH: 3,
                TraitLevel.VERY_HIGH: 4,
            },
            n=4,
        )
        result = gradient(rows, trait="openness", arm="traits_5")
        assert list(result.shares) == [level.value for level in TraitLevel]
        assert list(result.shares.values()) == [0.0, 0.25, 0.5, 0.75, 1.0]

    def test_the_two_segments_are_reported_against_the_control_level(self):
        """The design's claim is divergence *from the control*, so each extreme is
        reported against MEDIUM as well as against the other extreme."""
        rows = sweep_rows(
            {
                TraitLevel.VERY_LOW: 0,
                TraitLevel.LOW: 1,
                TraitLevel.MEDIUM: 2,
                TraitLevel.HIGH: 3,
                TraitLevel.VERY_HIGH: 4,
            },
            n=4,
        )
        result = gradient(rows, trait="openness", arm="traits_5")
        assert result.target_lift == pytest.approx(0.5)
        assert result.opposite_lift == pytest.approx(-0.5)

    def test_span_is_the_target_minus_the_opposite_segment(self):
        rows = sweep_rows(
            {
                TraitLevel.VERY_LOW: 1,
                TraitLevel.LOW: 2,
                TraitLevel.MEDIUM: 2,
                TraitLevel.HIGH: 2,
                TraitLevel.VERY_HIGH: 3,
            },
            n=4,
        )
        result = gradient(rows, trait="openness", arm="traits_5")
        assert result.span == pytest.approx(0.5)
        assert result.monotone is True

    def test_a_flat_gradient_is_monotone_but_has_no_span(self):
        """Monotonicity alone proves nothing — it must be read with the span."""
        rows = sweep_rows({level: 2 for level in TraitLevel}, n=4)
        result = gradient(rows, trait="openness", arm="traits_5")
        assert result.monotone is True
        assert result.span == 0.0
        assert result.span_z == 0.0

    def test_a_unanimous_flat_gradient_does_not_divide_by_zero(self):
        rows = sweep_rows({level: 0 for level in TraitLevel}, n=4)
        result = gradient(rows, trait="openness", arm="traits_5")
        assert result.span == 0.0
        assert result.span_z == 0.0

    def test_a_reversed_gradient_is_not_monotone(self):
        rows = sweep_rows(
            {
                TraitLevel.VERY_LOW: 4,
                TraitLevel.LOW: 3,
                TraitLevel.MEDIUM: 2,
                TraitLevel.HIGH: 1,
                TraitLevel.VERY_HIGH: 0,
            },
            n=4,
        )
        result = gradient(rows, trait="openness", arm="traits_5")
        assert result.monotone is False
        assert result.span == pytest.approx(-1.0)

    def test_a_wider_span_on_more_votes_is_more_significant(self):
        few = gradient(
            sweep_rows(
                {level: 2 for level in TraitLevel} | {TraitLevel.VERY_HIGH: 4}, n=4
            ),
            trait="openness",
            arm="traits_5",
        )
        many = gradient(
            sweep_rows(
                {level: 10 for level in TraitLevel} | {TraitLevel.VERY_HIGH: 20}, n=20
            ),
            trait="openness",
            arm="traits_5",
        )
        assert few.span == pytest.approx(many.span)
        assert many.span_z > few.span_z

    def test_the_null_share_is_pooled_so_a_maximal_span_stays_finite(self):
        """Both extremes estimate the null share, so the only degenerate case —
        se = 0 — is the one where the span is 0 too."""
        rows = sweep_rows(
            {level: 0 for level in TraitLevel} | {TraitLevel.VERY_HIGH: 4}, n=4
        )
        result = gradient(rows, trait="openness", arm="traits_5")
        assert result.span == pytest.approx(1.0)
        assert math.isfinite(result.span_z)
        assert result.span_z == pytest.approx(1.0 / math.sqrt(2 * 0.5 * 0.5 / 4))

    def test_an_empty_level_is_refused(self):
        rows = sweep_rows({TraitLevel.VERY_LOW: 1, TraitLevel.VERY_HIGH: 1}, n=2)
        with pytest.raises(ValueError, match="no votes"):
            gradient(rows, trait="openness", arm="traits_5")


class TestControlsOnTheRun:
    def test_control_share_reads_the_control_pair_only(self):
        rows = [
            row(pair_id="control", chosen=HIGH),
            row(pair_id="control", chosen=HIGH, replicate=1),
            row(pair_id="openness", chosen=LOW, replicate=2),
        ]
        assert control_share(rows) == 1.0

    def test_position_bias_is_the_share_choosing_whatever_was_shown_first(self):
        rows = [
            row(order=HIGH, chosen=HIGH),
            row(order=LOW, chosen=LOW, replicate=1),
            row(order=HIGH, chosen=LOW, replicate=2),
            row(order=LOW, chosen=LOW, replicate=3),
        ]
        assert position_bias(rows) == pytest.approx(0.75)
