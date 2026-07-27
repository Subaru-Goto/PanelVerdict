from math import comb

import pytest
from scipy import integrate, stats

from app.schemas import VoteRecord
from app.verdict import (
    _confirmed,
    expected_preference_shortfall,
    panel_progress,
    posterior,
    rope_verdict,
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


def test_tally_votes_counts_and_picks_winner() -> None:
    records = [_vote("vA"), _vote("vA"), _vote("vB")]

    verdict = tally_votes(records, variant_ids=["vA", "vB"])

    assert verdict.counts == {"vA": 2, "vB": 1}
    assert verdict.total == 3
    assert verdict.winner == "vA"


def test_tally_votes_zero_fills_variant_with_no_votes() -> None:
    records = [_vote("vA"), _vote("vA")]

    verdict = tally_votes(records, variant_ids=["vA", "vB"])

    assert verdict.counts == {"vA": 2, "vB": 0}  # vB never chosen, still reported
    assert verdict.total == 2
    assert verdict.winner == "vA"


def test_tally_votes_breaks_tie_by_variant_ids_order() -> None:
    # vB is encountered first, but the tiebreak must follow variant_ids order,
    # not the order votes happened to arrive in.
    records = [_vote("vB"), _vote("vA")]

    verdict = tally_votes(records, variant_ids=["vA", "vB"])

    assert verdict.counts == {"vA": 1, "vB": 1}
    assert verdict.winner == "vA"  # tie -> first in variant_ids order


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
        """The case that chose the HDI over the equal-tailed interval (009).

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
        """The signed-off default lives in one place; a v2 per-test band reuses
        this function unchanged."""
        assert rope_verdict((0.580, 0.700), rope=(0.45, 0.55)) == "decisive"
        assert rope_verdict((0.46, 0.54), rope=(0.45, 0.55)) == "practical_tie"

    def test_one_vote_separates_decisive_from_undecided_at_n_200(self) -> None:
        """The boundary sensitivity documented in reading-the-posterior.md,
        asserted end-to-end so the doc's claim cannot drift from the code."""
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


class TestPanelProgress:
    def test_it_accumulates_across_batches(self) -> None:
        """Batches report what they alone did; accumulating is this function's job,
        because a conjugate update is just addition and a caller doing it by hand is
        a place to get it wrong."""
        result = panel_progress([(12, 20), (11, 20), (14, 20)])
        assert [(b.preferring_b, b.total) for b in result.batches] == [
            (12, 20),
            (23, 40),
            (37, 60),
        ]

    def test_every_batch_carries_what_it_implied_at_the_time(self) -> None:
        """The animation needs the interval per batch, not only at the end."""
        result = panel_progress([(15, 20), (15, 20)])
        first, second = result.batches
        assert first.posterior.total == 20
        assert second.posterior.total == 40
        first_width = first.posterior.interval[1] - first.posterior.interval[0]
        second_width = second.posterior.interval[1] - second.posterior.interval[0]
        assert second_width < first_width

    def test_by_default_it_never_stops_early(self) -> None:
        """The measured default: peeking inflates false decisive ~25-fold and saves
        about twenty cents, so the whole panel is always spent."""
        result = panel_progress([(20, 20)] * 5)
        assert len(result.batches) == 5
        assert result.stopped_early is False
        assert result.batches[0].verdict == "decisive"

    def test_stopping_needs_the_verdict_confirmed_not_merely_reached(self) -> None:
        result = panel_progress([(20, 20)] * 5, stop_early=True, confirmations=3)
        assert len(result.batches) == 3
        assert result.stopped_early is True

    def test_one_confirmation_reproduces_the_naive_rule(self) -> None:
        result = panel_progress([(20, 20)] * 5, stop_early=True, confirmations=1)
        assert len(result.batches) == 1
        assert result.stopped_early is True

    def test_a_flip_flopping_verdict_never_confirms(self) -> None:
        """The failure the streak exists to catch: a run that crosses a ROPE edge and
        falls back has not settled anything."""
        assert _confirmed(["decisive", "undecided", "decisive"], 3) is False
        assert _confirmed(["decisive", "decisive", "undecided"], 3) is False
        assert _confirmed(["undecided", "decisive", "decisive", "decisive"], 3) is True

    def test_a_run_of_undecided_is_not_a_confirmation(self) -> None:
        assert _confirmed(["undecided"] * 5, 3) is False

    def test_the_two_definite_verdicts_do_not_confirm_each_other(self) -> None:
        """Both are actionable but they are not the same answer, so a streak mixing
        them has settled nothing."""
        assert _confirmed(["decisive", "practical_tie", "decisive"], 3) is False
        assert _confirmed(["practical_tie"] * 3, 3) is True

    def test_reaching_the_last_batch_is_not_stopping_early(self) -> None:
        result = panel_progress([(20, 20)] * 3, stop_early=True, confirmations=3)
        assert len(result.batches) == 3
        assert result.stopped_early is False

    def test_the_final_batch_is_the_reportable_one(self) -> None:
        result = panel_progress([(12, 20), (11, 20)])
        assert result.final is result.batches[-1]
        assert result.final.total == 40

    def test_a_panel_with_no_batches_is_a_caller_error(self) -> None:
        with pytest.raises(ValueError, match="at least one batch"):
            panel_progress([])

    def test_an_impossible_batch_is_refused(self) -> None:
        with pytest.raises(ValueError):
            panel_progress([(21, 20)])

    def test_the_band_flows_through_to_every_batch(self) -> None:
        """Asserted by the band changing an outcome, not merely being accepted: a
        26/40 split is a tie inside a wide band and undecided inside the default."""
        per_batch = [(13, 20), (13, 20)]
        assert [b.verdict for b in panel_progress(per_batch).batches] == [
            "undecided",
            "undecided",
        ]
        assert [
            b.verdict for b in panel_progress(per_batch, rope=(0.2, 0.8)).batches
        ] == ["undecided", "practical_tie"]
