import math

import numpy as np
import pytest

from app.bigfive import MU, mu_for
from app.pool_overview import (
    age_band_of,
    bigfive_comparisons,
    correlation_deviations,
    demographic_deviations,
    format_report,
    worst_deviation,
)
from app.sampler import JointCell
from app.schemas import BigFive, Persona

BANDS = ("18-19", "20-29", "30-39", "80+")


def persona(id_: str, *, age: int = 34, gender: str = "female", **overrides) -> Persona:
    base = dict(
        country="US",
        age=age,
        gender=gender,
        income_quintile=3,
        education="tertiary",
        big_five=_varied(int(id_.rsplit("-", 1)[-1])),
    )
    return Persona(id=id_, **(base | overrides))


def _varied(seed: int) -> BigFive:
    """Traits that actually differ, so correlations are defined — a pool of clones
    has zero variance and every correlation becomes 0/0."""
    values = np.random.default_rng(seed).normal(size=5)
    return BigFive(**dict(zip(BigFive.model_fields, values.tolist())))


class TestAgeBandOf:
    def test_a_closed_band_contains_both_endpoints(self):
        assert age_band_of(18, BANDS) == "18-19"
        assert age_band_of(19, BANDS) == "18-19"
        assert age_band_of(20, BANDS) == "20-29"

    def test_an_open_band_has_no_upper_bound(self):
        assert age_band_of(80, BANDS) == "80+"
        assert age_band_of(100, BANDS) == "80+"

    def test_an_age_in_no_band_is_refused_rather_than_silently_binned(self):
        with pytest.raises(ValueError, match="no age band"):
            age_band_of(50, BANDS)


class TestDemographicDeviations:
    def test_a_pool_matching_its_table_deviates_by_nothing(self):
        cells = [
            JointCell(
                age_band="20-29",
                gender=gender,
                education="tertiary",
                income_quintile=3,
                weight=1.0,
            )
            for gender in ("male", "female")
        ]
        pool = [persona(f"US-{i}", age=25, gender="male") for i in range(50)] + [
            persona(f"US-{50 + i}", age=25, gender="female") for i in range(50)
        ]
        deviations = demographic_deviations(pool, {"US": cells})
        assert {d.realized for d in deviations if d.dimension == "gender"} == {0.5}
        assert all(d.z == pytest.approx(0.0) for d in deviations)

    def test_a_skewed_pool_reports_the_gap_in_standard_errors(self):
        """60/40 against a 50/50 target, n=100: z = 0.10 / sqrt(.25/100) = 2.0."""
        cells = [
            JointCell(
                age_band="20-29",
                gender=gender,
                education="tertiary",
                income_quintile=3,
                weight=1.0,
            )
            for gender in ("male", "female")
        ]
        pool = [persona(f"US-{i}", age=25, gender="male") for i in range(60)] + [
            persona(f"US-{60 + i}", age=25, gender="female") for i in range(40)
        ]
        male = next(
            d
            for d in demographic_deviations(pool, {"US": cells})
            if d.category == "male"
        )
        assert male.target == pytest.approx(0.5)
        assert male.realized == pytest.approx(0.6)
        assert male.z == pytest.approx(2.0)

    def test_countries_are_compared_separately_so_errors_cannot_cancel(self):
        """Pooled, an all-male US and an all-female JP average to a clean 50/50 that
        neither country's table supports. Each table is its own claim."""
        balanced = [
            JointCell(
                age_band="20-29",
                gender=gender,
                education="tertiary",
                income_quintile=3,
                weight=1.0,
            )
            for gender in ("male", "female")
        ]
        pool = [persona(f"US-{i}", age=25, gender="male") for i in range(50)] + [
            persona(f"JP-{i}", age=25, gender="female", country="JP") for i in range(50)
        ]
        deviations = demographic_deviations(
            pool, {"US": balanced, "JP": list(balanced)}
        )
        by_country = {
            (d.country, d.category): d for d in deviations if d.dimension == "gender"
        }
        assert by_country[("US", "male")].realized == 1.0
        assert by_country[("JP", "male")].realized == 0.0
        assert abs(by_country[("US", "male")].z) > 7
        assert abs(by_country[("JP", "male")].z) > 7

    def test_a_draw_the_table_calls_impossible_is_infinite_not_perfect(self):
        """Zero target means zero sampling error, so the naive z is 0/0. Reporting
        that as 0.0 would render the worst sampler bug there is as a clean score."""
        cells = [
            JointCell(
                age_band="20-29",
                gender="male",
                education="tertiary",
                income_quintile=3,
                weight=1.0,
            )
        ]
        pool = [persona(f"US-{i}", age=25, gender="female") for i in range(10)]
        female = next(
            d
            for d in demographic_deviations(pool, {"US": cells})
            if d.category == "female"
        )
        assert female.target == 0.0
        assert math.isinf(female.z)


class TestBigFiveComparisons:
    def test_one_demographic_cell_expects_that_cell_s_mu_and_unit_sd(self):
        """With every persona in one cell there is no between-cell variance, so
        Cov(mu) vanishes and the pool's spread is Sigma's alone."""
        pool = [persona(f"US-{i}", age=25, gender="male") for i in range(100)]
        expected = MU["20-29|male"]
        for index, comparison in enumerate(bigfive_comparisons(pool)):
            assert comparison.expected_mean == pytest.approx(expected[index])
            assert comparison.expected_sd == pytest.approx(1.0)

    def test_two_cells_widen_the_expected_spread_beyond_sigma(self):
        """The law of total variance: Var(X) = Sigma_ii + Var(mu). A pool spanning
        two demographic cells must be expected to spread wider than Sigma alone,
        and a check against sd=1 would fail a correct sampler."""
        pool = [persona(f"US-{i}", age=25, gender="male") for i in range(50)] + [
            persona(f"US-{50 + i}", age=85, gender="female") for i in range(50)
        ]
        young, old = mu_for(25, "male"), mu_for(85, "female")
        for index, comparison in enumerate(bigfive_comparisons(pool)):
            midpoint = (young[index] + old[index]) / 2
            half_gap = abs(young[index] - old[index]) / 2
            assert comparison.expected_mean == pytest.approx(midpoint)
            assert comparison.expected_sd == pytest.approx(math.sqrt(1.0 + half_gap**2))

    def test_the_realized_moments_are_the_sample_moments(self):
        scores = [-1.0, 0.0, 1.0]
        pool = [
            persona(
                f"US-{i}",
                age=25,
                gender="male",
                big_five=BigFive(
                    openness=score,
                    conscientiousness=0.0,
                    extraversion=0.0,
                    agreeableness=0.0,
                    neuroticism=0.0,
                ),
            )
            for i, score in enumerate(scores)
        ]
        openness = bigfive_comparisons(pool)[0]
        assert openness.realized_mean == pytest.approx(0.0)
        assert openness.realized_sd == pytest.approx(1.0)

    def test_a_pool_drawn_off_its_prior_shows_up_in_standard_errors(self):
        pool = [
            persona(
                f"US-{i}",
                age=25,
                gender="male",
                big_five=BigFive(
                    openness=5.0,
                    conscientiousness=0.0,
                    extraversion=0.0,
                    agreeableness=0.0,
                    neuroticism=0.0,
                ),
            )
            for i in range(100)
        ]
        assert bigfive_comparisons(pool)[0].mean_z > 10


class TestCorrelationDeviations:
    def test_perfectly_correlated_traits_deviate_from_the_prior(self):
        pool = [
            persona(
                f"US-{i}",
                age=25,
                gender="male",
                big_five=BigFive(
                    openness=float(i),
                    conscientiousness=float(i),
                    extraversion=float((-1) ** i),
                    agreeableness=float(i % 3),
                    neuroticism=float(i % 5),
                ),
            )
            for i in range(50)
        ]
        worst = correlation_deviations(pool)[0]
        assert {worst.trait_a, worst.trait_b} == {"openness", "conscientiousness"}
        assert worst.realized == pytest.approx(1.0)

    def test_deviations_are_ordered_worst_first(self):
        pool = [persona(f"US-{i}", age=25, gender="male") for i in range(10)]
        gaps = [abs(d.realized - d.expected) for d in correlation_deviations(pool)]
        assert gaps == sorted(gaps, reverse=True)


class TestWorstDeviation:
    def test_it_finds_the_largest_gap_across_both_panels(self):
        cells = [
            JointCell(
                age_band="20-29",
                gender=gender,
                education="tertiary",
                income_quintile=3,
                weight=1.0,
            )
            for gender in ("male", "female")
        ]
        pool = [
            persona(
                f"US-{i}",
                age=25,
                gender="male",
                big_five=BigFive(
                    openness=5.0,
                    conscientiousness=float(i % 3),
                    extraversion=float(i % 5),
                    agreeableness=float(-(i % 3)),
                    neuroticism=float(i % 7),
                ),
            )
            for i in range(100)
        ]
        label, z = worst_deviation(
            demographic_deviations(pool, {"US": cells}), bigfive_comparisons(pool)
        )
        assert label == "openness mean"
        assert z > 10


class TestReport:
    def test_the_report_names_every_panel_and_the_pool_size(self):
        pool = [persona(f"US-{i}", age=25, gender="male") for i in range(20)]
        report = format_report(pool)
        assert "20" in report
        for heading in ("Demographics", "Big Five", "Correlations"):
            assert heading in report

    def test_the_header_reports_the_worst_gap_and_how_many_were_compared(self):
        """A z means nothing without the count — across ~30 comparisons a healthy
        pool exceeds 2 more often than not."""
        pool = [persona(f"US-{i}", age=25, gender="male") for i in range(20)]
        header = format_report(pool).splitlines()[2]
        assert "comparisons" in header
        assert "z = " in header
