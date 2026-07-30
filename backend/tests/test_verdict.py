from math import comb

import pytest
from scipy import integrate, stats

from app.schemas import VoteRecord
from app.verdict import (
    _ROPE,
    detectable_gap,
    expected_preference_shortfall,
    panel_verdict,
    posterior,
    probability_meaningfully_preferred,
    probability_practical_tie,
    rope_verdict,
    stopping_decision,
    tally_votes,
)


def _vote(chosen_variant_id: str) -> VoteRecord:
    """A VoteRecord where only chosen_variant_id matters to the tally."""
    return VoteRecord(
        persona_id="p",
        test_id="t",
        chosen_variant_id=chosen_variant_id,
        presentation_order=["vA", "vB"],
        reason="r",
    )


def test_tally_votes_counts_without_naming_a_winner() -> None:
    """A count leader carries no uncertainty and used an arbitrary tiebreak, so the
    tally reports the numbers and `panel_verdict` decides."""
    records = [_vote("vA"), _vote("vA"), _vote("vB")]

    tally = tally_votes(records, variant_ids=["vA", "vB"])

    assert tally.counts == {"vA": 2, "vB": 1}
    assert tally.total == 3
    assert not hasattr(tally, "winner")


def test_tally_votes_zero_fills_variant_with_no_votes() -> None:
    records = [_vote("vA"), _vote("vA")]

    verdict = tally_votes(records, variant_ids=["vA", "vB"])

    assert verdict.counts == {"vA": 2, "vB": 0}  # vB never chosen, still reported
    assert verdict.total == 2


def test_tally_votes_reports_a_tie_as_a_tie() -> None:
    """The old arbitrary tiebreak is gone: an even split is just an even split."""
    records = [_vote("vA"), _vote("vB")]

    tally = tally_votes(records, variant_ids=["vA", "vB"])

    assert tally.counts == {"vA": 1, "vB": 1}


class TestPosterior:
    def test_the_probability_matches_the_exact_binomial_sum(self) -> None:
        """An independent route to the same number.

        A flat prior over integer counts makes the posterior Beta(integer,
        integer), and for integer parameters P(p > 0.5) is a finite binomial sum —
        arithmetic the implementation never performs, so the two can disagree.
        """
        for preferring_b, total in [(3, 5), (7, 10), (60, 100), (90, 100)]:
            expected = sum(
                comb(total + 1, i) for i in range(preferring_b + 1)
            ) * 0.5 ** (total + 1)
            result = posterior(preferring_b=preferring_b, total=total)
            assert result.probability_majority_prefers_b == pytest.approx(expected)

    def test_the_share_is_pulled_toward_a_tie_by_the_prior(self) -> None:
        """Not k/n. Six of ten votes is 0.60 raw and 7/12 after the flat prior,
        which is the shrinkage that stops a small sample overstating itself."""
        assert posterior(preferring_b=6, total=10).share_preferring_b == pytest.approx(
            7 / 12
        )

    def test_no_votes_returns_the_prior_rather_than_failing(self) -> None:
        result = posterior(preferring_b=0, total=0)
        assert result.share_preferring_b == pytest.approx(0.5)
        assert result.probability_majority_prefers_b == pytest.approx(0.5)

    def test_the_interval_holds_the_mass_with_equal_density_at_its_ends(self) -> None:
        """The defining property of a highest-density interval, asserted instead of
        fixed endpoints so the test survives a change of solver."""
        for preferring_b, total in [(60, 100), (8, 10), (120, 200)]:
            result = posterior(preferring_b=preferring_b, total=total)
            lo, hi = result.interval
            dist = stats.beta(1 + preferring_b, 1 + total - preferring_b)

            assert dist.cdf(hi) - dist.cdf(lo) == pytest.approx(0.95, abs=1e-6)
            assert dist.pdf(lo) == pytest.approx(dist.pdf(hi), rel=1e-3)

    def test_a_skewed_posterior_excludes_the_tie_where_equal_tails_would_not(
        self,
    ) -> None:
        """The case that chose the HDI over the equal-tailed interval.

        Eight of ten votes: the equal-tailed interval starts at 0.482 and so admits
        a tie, the HDI starts above 0.5 and does not. Same posterior, opposite
        answers — pin it, or the decision can be reverted without a failure.
        """
        lo, hi = posterior(preferring_b=8, total=10).interval
        dist = stats.beta(9, 3)

        assert lo > 0.5
        assert (lo, hi) == pytest.approx((0.5163, 0.9594), abs=5e-4)
        assert lo > dist.ppf(0.025)
        assert hi > dist.ppf(0.975)

    def test_a_unanimous_panel_runs_the_interval_to_the_boundary(self) -> None:
        """With no votes for A the density is monotone, so the shortest interval
        sits against 1.0 rather than inside — the interior solver would miss it."""
        lo, hi = posterior(preferring_b=10, total=10).interval
        assert hi == 1.0
        assert lo == pytest.approx(stats.beta(11, 1).ppf(0.05))

    @pytest.mark.parametrize(
        ("preferring_b", "total"), [(-1, 10), (11, 10), (0, -1), (3, 2)]
    )
    def test_counts_outside_the_panel_are_refused(
        self, preferring_b: int, total: int
    ) -> None:
        with pytest.raises(ValueError):
            posterior(preferring_b=preferring_b, total=total)


class TestRopeVerdict:
    def test_an_interval_clear_of_the_band_is_decisive(self) -> None:
        assert rope_verdict((0.580, 0.700)) == "decisive"

    def test_an_interval_entirely_below_the_band_is_decisive_for_a(self) -> None:
        """A winning is a verdict too — a rule keyed only off the upper edge
        would call every A-victory undecided."""
        assert rope_verdict((0.300, 0.420)) == "decisive"

    def test_an_interval_inside_the_band_is_a_practical_tie(self) -> None:
        assert rope_verdict((0.485, 0.520)) == "practical_tie"

    def test_an_interval_straddling_an_edge_is_undecided(self) -> None:
        assert rope_verdict((0.550, 0.620)) == "undecided"

    def test_touching_the_edge_is_undecided(self) -> None:
        """Deliberate: 0.57 is *in* the band (a share of exactly 0.57 is a
        negligible difference by the band's own definition), so an interval
        reaching it has mass on a negligible value and may not claim decisive."""
        assert rope_verdict((0.570, 0.666)) == "undecided"
        assert rope_verdict((0.485, 0.570)) == "practical_tie"

    def test_the_band_is_a_parameter_not_a_constant(self) -> None:
        """The default lives in one place, so a caller can probe another band
        without reaching into the module."""
        assert rope_verdict((0.580, 0.700), rope=(0.45, 0.55)) == "decisive"
        assert rope_verdict((0.46, 0.54), rope=(0.45, 0.55)) == "practical_tie"

    def test_one_vote_separates_decisive_from_undecided_at_n_200(self) -> None:
        """One vote separates the two verdicts here, so "decisive" must not be
        read as robust. Asserted end-to-end so the claim cannot drift."""
        assert rope_verdict(posterior(preferring_b=128, total=200).interval) == (
            "decisive"
        )
        assert rope_verdict(posterior(preferring_b=127, total=200).interval) == (
            "undecided"
        )

    def test_a_nonsense_band_is_refused(self) -> None:
        with pytest.raises(ValueError):
            rope_verdict((0.4, 0.6), rope=(0.53, 0.47))


class TestExpectedPreferenceShortfall:
    def _numeric(self, k: int, total: int, *, toward: str) -> float:
        """Integrate the shortfall directly — an independent route to the closed
        form the implementation uses (two Beta CDFs, no integration)."""
        density = stats.beta(1 + k, 1 + total - k).pdf
        if toward == "b":
            return integrate.quad(lambda p: (0.5 - p) * density(p), 0.0, 0.5)[0]
        return integrate.quad(lambda p: (p - 0.5) * density(p), 0.5, 1.0)[0]

    @pytest.mark.parametrize(
        ("preferring_b", "total"), [(8, 10), (60, 100), (120, 200), (30, 50), (2, 7)]
    )
    def test_it_matches_direct_integration(self, preferring_b: int, total: int) -> None:
        result = expected_preference_shortfall(preferring_b=preferring_b, total=total)
        assert result.shipping_b == pytest.approx(
            self._numeric(preferring_b, total, toward="b"), abs=1e-9
        )
        assert result.shipping_a == pytest.approx(
            self._numeric(preferring_b, total, toward="a"), abs=1e-9
        )

    def test_it_decomposes_into_likelihood_times_magnitude(self) -> None:
        """The reported number is P(B worse) x average shortfall in that branch —
        8 of 10 votes is a 3.3% chance of being wrong by 5.8 points."""
        result = expected_preference_shortfall(preferring_b=8, total=10)
        probability_b_worse = stats.beta(9, 3).cdf(0.5)

        assert probability_b_worse == pytest.approx(0.0327, abs=5e-4)
        assert result.shipping_b / probability_b_worse == pytest.approx(
            0.0578, abs=5e-4
        )
        assert result.shipping_b == pytest.approx(0.00189, abs=5e-6)

    def test_confidence_alone_does_not_determine_the_shortfall(self) -> None:
        """Why this exists beside P(majority): two panels of near-equal confidence
        differ several-fold in exposure, because a small panel has fat tails — if
        it is wrong, it is wrong by more."""
        small = posterior(preferring_b=8, total=10)
        large = posterior(preferring_b=60, total=100)
        assert small.probability_majority_prefers_b == pytest.approx(0.967, abs=1e-3)
        assert large.probability_majority_prefers_b == pytest.approx(0.977, abs=1e-3)

        exposed = expected_preference_shortfall(preferring_b=8, total=10).shipping_b
        safer = expected_preference_shortfall(preferring_b=60, total=100).shipping_b
        assert exposed > 4 * safer

    def test_the_two_directions_are_symmetric_under_swapping_the_variants(self) -> None:
        forward = expected_preference_shortfall(preferring_b=8, total=10)
        reversed_ = expected_preference_shortfall(preferring_b=2, total=10)
        assert forward.shipping_b == pytest.approx(reversed_.shipping_a)
        assert forward.shipping_a == pytest.approx(reversed_.shipping_b)

    def test_an_even_split_exposes_both_choices_equally(self) -> None:
        result = expected_preference_shortfall(preferring_b=5, total=10)
        assert result.shipping_a == pytest.approx(result.shipping_b)

    def test_no_votes_reports_the_prior_exposure(self) -> None:
        """Uniform over [0,1], so the integral is 0.5^2/2 = 1/8 either way — a
        quarter of the whole scale, which is what "we know nothing" costs."""
        result = expected_preference_shortfall(preferring_b=0, total=0)
        assert result.shipping_b == pytest.approx(1 / 8)
        assert result.shipping_a == pytest.approx(1 / 8)

    def test_impossible_counts_are_refused(self) -> None:
        with pytest.raises(ValueError):
            expected_preference_shortfall(preferring_b=11, total=10)


class TestStoppingDecision:
    """The continuous rule chosen over label agreement: stop when the report
    would already make a call. Expected values are the published table plus the
    verified tie readings, not recomputations."""

    def test_a_clear_lead_stops_as_decisive(self) -> None:
        assert stopping_decision(preferring_b=66, total=100) == "decisive"
        assert stopping_decision(preferring_b=67, total=100) == "decisive"

    def test_a_lead_for_a_stops_too(self) -> None:
        """Direction-blind: A winning ends the run exactly like B winning."""
        assert stopping_decision(preferring_b=33, total=100) == "decisive"

    def test_just_under_the_bar_continues(self) -> None:
        """65/100 is the split the old label got wrong at 0.946 — and 0.946 is
        still under 0.95, so the run keeps buying votes rather than calling it."""
        assert stopping_decision(preferring_b=65, total=100) is None

    def test_a_proven_tie_stops(self) -> None:
        """The stop the label rule could never take: an even split at n=200 is
        credibly inside the band (0.954), so more votes answer nothing."""
        assert stopping_decision(preferring_b=100, total=200) == "practical_tie"

    def test_an_unproven_tie_continues(self) -> None:
        """Equivalence is expensive: dead even at n=100 is only 0.84 inside the
        band, and at n=170 still 0.93 — the tie stop needs nearly the full cap."""
        assert stopping_decision(preferring_b=50, total=100) is None
        assert stopping_decision(preferring_b=85, total=170) is None

    def test_the_bar_is_the_credible_mass_not_a_new_constant(self) -> None:
        """65/100 continues at the default bar and stops at a lower one — the
        threshold is the caller's credibility, nothing invented here."""
        assert stopping_decision(preferring_b=65, total=100, credible_mass=0.9) == (
            "decisive"
        )


class TestPanelVerdictPayload:
    def test_it_carries_the_band_that_produced_it(self) -> None:
        """A verdict silent about which band produced it could be re-labelled
        later with nothing to notice."""
        result = panel_verdict(preferring_b=128, total=200)
        assert result.rope == (0.43, 0.57)

        narrow = panel_verdict(preferring_b=128, total=200, rope=(0.47, 0.53))
        assert narrow.rope == (0.47, 0.53)
        assert (
            narrow.probability_meaningfully_preferred.b
            > result.probability_meaningfully_preferred.b
        )

    def test_it_reports_the_posterior_and_both_exposures(self) -> None:
        result = panel_verdict(preferring_b=120, total=200)
        reference = posterior(preferring_b=120, total=200)
        exposure = expected_preference_shortfall(preferring_b=120, total=200)

        assert result.share_preferring_b == reference.share_preferring_b
        assert (
            result.probability_majority_prefers_b
            == reference.probability_majority_prefers_b
        )
        assert result.credible_interval == reference.interval
        assert result.credible_mass == 0.95
        assert result.expected_preference_shortfall.shipping_a == exposure.shipping_a
        assert result.expected_preference_shortfall.shipping_b == exposure.shipping_b

    def test_it_reports_the_band_as_probabilities_and_a_resolution(self) -> None:
        """The 65/100 row of the published table, the split the three-way label
        got wrong: 0.946 reported as `undecided`. Written as the published
        numbers rather than as calls to the same functions, so a mis-wired
        argument cannot agree."""
        result = panel_verdict(preferring_b=65, total=100)

        assert result.probability_meaningfully_preferred.b == pytest.approx(
            0.946, abs=5e-4
        )
        assert result.detectable_gap == pytest.approx(0.1667, abs=5e-4)
        # The three regions partition one posterior, so the payload's own numbers must
        # close — the only check that they came from the same split and the same band.
        assert (
            result.probability_meaningfully_preferred.a
            + result.probability_meaningfully_preferred.b
            + result.probability_practical_tie
        ) == pytest.approx(1.0)

    def test_the_payload_names_no_winner(self) -> None:
        assert "winner" not in panel_verdict(preferring_b=200, total=200).model_dump()


class TestMeaningfulPreference:
    """P(the share falls outside the band), which is what the three-way label replaced.

    The label collapses everything between dead-even and near-certain into `undecided`;
    these are the numbers it was collapsing.
    """

    def test_a_symmetric_split_leans_each_direction_equally(self) -> None:
        outside = probability_meaningfully_preferred(preferring_b=50, total=100)

        assert outside.a == pytest.approx(outside.b)

    def test_the_three_regions_account_for_the_whole_posterior(self) -> None:
        """Independent of how either tail is computed: whatever mass is not above the
        band or below it must be inside it, so the two tails cannot both drift."""
        outside = probability_meaningfully_preferred(preferring_b=63, total=100)
        inside = probability_practical_tie(preferring_b=63, total=100)

        assert outside.a + outside.b + inside == pytest.approx(1.0)

    def test_it_separates_splits_the_label_calls_identical(self) -> None:
        """The whole point. `rope_verdict` reads `undecided` at both of these, which is
        why a report built on the label cannot tell a coin-flip from a near-certainty."""
        even = probability_meaningfully_preferred(preferring_b=50, total=100)
        leaning = probability_meaningfully_preferred(preferring_b=65, total=100)

        assert (
            rope_verdict(posterior(preferring_b=50, total=100).interval) == "undecided"
        )
        assert (
            rope_verdict(posterior(preferring_b=65, total=100).interval) == "undecided"
        )
        assert even.b < 0.1
        assert leaning.b > 0.9

    def test_a_lopsided_panel_is_near_certain_in_one_direction_only(self) -> None:
        outside = probability_meaningfully_preferred(preferring_b=90, total=100)

        assert outside.b > 0.99
        assert outside.a < 0.01


class TestDetectableGap:
    """The smallest gap a panel of a given size could call decisive.

    This is what makes a thin panel's null result readable: "could have detected a gap
    this wide, found nothing" says something, where "undecided" does not.
    """

    @pytest.mark.parametrize("total", [25, 100, 200, 400])
    def test_the_gap_is_the_reported_lean_at_the_first_decisive_split(
        self, total: int
    ) -> None:
        """Two independent routes to the same number.

        The boundary is found by walking every split rather than by halving, so a broken
        bisection cannot agree with it. And the expectation is read off
        `share_preferring_b` rather than by dividing counts, which pins the *unit*: the
        gap has to be comparable with the share the report prints beside it, and that is
        a posterior mean pulled toward 0.5, not `k / n`.
        """
        first_decisive = next(
            k
            for k in range(total // 2, total + 1)
            if rope_verdict(posterior(preferring_b=k, total=total).interval)
            == "decisive"
        )
        reported = posterior(preferring_b=first_decisive, total=total)

        assert detectable_gap(total=total) == pytest.approx(
            reported.share_preferring_b - 0.5
        )

    @pytest.mark.parametrize("total", [1, 2, 3, 4])
    def test_below_five_votes_no_split_is_decisive(self, total: int) -> None:
        """The floor deliberately *not* legislated, shown to exist as arithmetic:
        below n=5 even a unanimous panel's interval cannot clear the band, so the
        gap is None — and a unanimous panel's preference probability stays under
        the 95% bar, so the render-time recommendation reads "no call" without any
        rule saying so. If either stops holding — a narrower band, a lower mass —
        the no-threshold decision needs relitigating, which is what this failing
        would signal."""
        assert detectable_gap(total=total) is None
        unanimous = probability_meaningfully_preferred(preferring_b=total, total=total)
        assert unanimous.b < 0.95

    def test_five_votes_is_where_a_verdict_first_becomes_reachable(self) -> None:
        """The edge accepted on the ticket, pinned from both sides: unanimous
        five-of-five is the smallest panel that clears the bar."""
        assert detectable_gap(total=5) is not None
        assert probability_meaningfully_preferred(preferring_b=5, total=5).b > 0.95

    def test_a_bigger_panel_detects_a_smaller_gap(self) -> None:
        """Sampled across doublings, not consecutive sizes. The boundary moves in whole
        votes, so one extra panelist can round the other way and widen the gap slightly —
        the trend is what holds, not every step of it."""
        gaps = [detectable_gap(total=n) for n in (25, 50, 100, 200, 400)]

        assert all(gap is not None for gap in gaps)
        assert gaps == sorted(gaps, reverse=True)

    def test_no_panel_can_detect_a_gap_inside_the_band(self) -> None:
        """A difference the band calls negligible is negligible at any sample size, so
        the gap can never fall below the band's own half-width however much is spent."""
        rope_half = _ROPE[1] - 0.5

        assert all(detectable_gap(total=n) > rope_half for n in (25, 200, 2000))

    def test_the_gap_tracks_the_analytic_prediction(self) -> None:
        """Checked against a different formula rather than against itself: a 95%
        interval half-width for a proportion near even is ~0.98/sqrt(n), so the gap
        should land near the band's half-width plus that."""
        for total in (100, 200, 400):
            predicted = 0.07 + 0.98 / total**0.5

            assert detectable_gap(total=total) == pytest.approx(predicted, abs=0.015)
