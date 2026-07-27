from math import comb

import pytest
from scipy import stats

from app.schemas import VoteRecord
from app.verdict import posterior, rope_verdict, tally_votes


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
        assert rope_verdict((0.531, 0.666)) == "decisive"

    def test_an_interval_entirely_below_the_band_is_decisive_for_a(self) -> None:
        """A winning is a verdict too — a rule keyed only off the upper edge
        would call every A-victory undecided."""
        assert rope_verdict((0.334, 0.469)) == "decisive"

    def test_an_interval_inside_the_band_is_a_practical_tie(self) -> None:
        assert rope_verdict((0.485, 0.520)) == "practical_tie"

    def test_an_interval_straddling_an_edge_is_undecided(self) -> None:
        assert rope_verdict((0.495, 0.560)) == "undecided"

    def test_touching_the_edge_is_undecided(self) -> None:
        """Deliberate: 0.53 is *in* the band (a share of exactly 0.53 is a
        negligible difference by the band's own definition), so an interval
        reaching it has mass on a negligible value and may not claim decisive."""
        assert rope_verdict((0.530, 0.666)) == "undecided"
        assert rope_verdict((0.485, 0.530)) == "practical_tie"

    def test_the_band_is_a_parameter_not_a_constant(self) -> None:
        """The signed-off default lives in one place; a v2 per-test band reuses
        this function unchanged."""
        assert rope_verdict((0.531, 0.666), rope=(0.45, 0.55)) == "undecided"
        assert rope_verdict((0.46, 0.54), rope=(0.45, 0.55)) == "practical_tie"

    def test_one_vote_separates_decisive_from_undecided_at_n_200(self) -> None:
        """The boundary sensitivity documented in reading-the-posterior.md,
        asserted end-to-end so the doc's claim cannot drift from the code."""
        assert rope_verdict(posterior(preferring_b=120, total=200).interval) == (
            "decisive"
        )
        assert rope_verdict(posterior(preferring_b=119, total=200).interval) == (
            "undecided"
        )

    def test_a_nonsense_band_is_refused(self) -> None:
        with pytest.raises(ValueError):
            rope_verdict((0.4, 0.6), rope=(0.53, 0.47))
