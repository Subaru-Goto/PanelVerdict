import operator

import numpy as np
import pytest

from app.bigfive import (
    _mu_band,
    bigfive_from_levels,
    bucketize,
    LEVEL_BOUNDS,
    MU,
    sample_big_five,
    SIGMA,
)
from app.schemas import TRAIT_ORDER, TraitLevel
from pipeline.derive_bigfive_norms import AGE_BANDS


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (-3.0, TraitLevel.VERY_LOW),
        (-1.6, TraitLevel.VERY_LOW),
        (-1.5, TraitLevel.LOW),  # boundaries belong to the inner band
        (-0.6, TraitLevel.LOW),
        (-0.5, TraitLevel.MEDIUM),
        (0.0, TraitLevel.MEDIUM),
        (0.5, TraitLevel.MEDIUM),
        (0.6, TraitLevel.HIGH),
        (1.5, TraitLevel.HIGH),
        (1.6, TraitLevel.VERY_HIGH),
        (3.0, TraitLevel.VERY_HIGH),
    ],
)
def test_bucketize(score, level):
    assert bucketize(score) == level


def test_bucketize_splits_a_normal_population_into_usable_levels():
    # the cutoffs are round z-values; what justifies them is the split they
    # produce on a normal population — 6.7 / 24.2 / 38.3 / 24.2 / 6.7, so no
    # level is too rare to render. Asserted rather than commented, because a
    # tweak to either cutoff silently changes how the whole pool reads.
    draws = np.random.default_rng(0).normal(size=200_000)
    shares = {level: 0.0 for level in TraitLevel}
    for score in draws:
        shares[bucketize(float(score))] += 1 / len(draws)

    assert shares[TraitLevel.VERY_LOW] == pytest.approx(0.067, abs=0.005)
    assert shares[TraitLevel.LOW] == pytest.approx(0.242, abs=0.005)
    assert shares[TraitLevel.MEDIUM] == pytest.approx(0.383, abs=0.005)
    assert shares[TraitLevel.HIGH] == pytest.approx(0.242, abs=0.005)
    assert shares[TraitLevel.VERY_HIGH] == pytest.approx(0.067, abs=0.005)


def test_bigfive_from_levels_round_trips_through_bucketize():
    # the representative score for each level must bucketize back to that level,
    # i.e. every _LEVEL_SCORE sits inside its own band — locks that coupling
    for level in TraitLevel:
        bf = bigfive_from_levels(
            openness=level,
            conscientiousness=level,
            extraversion=level,
            agreeableness=level,
            neuroticism=level,
        )
        assert all(bucketize(score) == level for _, score in bf)


_COMPARISONS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


def _admits(level: TraitLevel, score: float) -> bool:
    """Apply a requested level's bounds the way the SQL does — one comparison each."""
    return all(_COMPARISONS[op](score, value) for op, value in LEVEL_BOUNDS[level])


_SWEEP = [round(score, 2) for score in np.arange(-3.0, 3.01, 0.05)]


def test_a_requested_level_admits_every_score_that_renders_as_it():
    # the safe direction of the round trip, and the one a target depends on: whoever
    # the pool *renders* as high must be reachable by a request for high. The other
    # direction is false by design — see the nesting test below.
    for score in _SWEEP:
        assert _admits(bucketize(score), score), score


def test_the_outer_levels_nest_inside_the_inner_ones():
    # what directionality exists to create: asking for cautious people must not
    # exclude the *most* cautious. So `high` admits everyone `very_high` admits, and
    # the levels are nested rather than a partition — a test asserting disjointness
    # would pass on the wrong property and hide a bound that had drifted back to exact.
    for score in _SWEEP:
        if _admits(TraitLevel.VERY_HIGH, score):
            assert _admits(TraitLevel.HIGH, score), score
        if _admits(TraitLevel.VERY_LOW, score):
            assert _admits(TraitLevel.LOW, score), score


@pytest.mark.parametrize(
    ("score", "admitted_by"),
    [
        # the boundaries, which is where the two cutoffs could drift apart: each
        # belongs to the inner band in bucketize, so the bound has to exclude it
        (0.5, {TraitLevel.MEDIUM}),  # bucketize says MEDIUM, so `high` must refuse it
        (0.51, {TraitLevel.HIGH}),
        (1.5, {TraitLevel.HIGH}),  # bucketize says HIGH, so `very_high` must refuse it
        (1.51, {TraitLevel.HIGH, TraitLevel.VERY_HIGH}),
        (-0.5, {TraitLevel.MEDIUM}),
        (-0.51, {TraitLevel.LOW}),
        (-1.5, {TraitLevel.LOW}),
        (-1.51, {TraitLevel.LOW, TraitLevel.VERY_LOW}),
    ],
)
def test_a_threshold_is_exactly_bucketize_s_own_boundary(score, admitted_by):
    assert {level for level in TraitLevel if _admits(level, score)} == admitted_by


def test_only_the_middle_is_a_band():
    # "average" means the middle, so `medium` is the one level bounded both ways.
    # Every other level is a single open-ended comparison, which is what the SQL
    # builder has to be able to handle.
    assert len(LEVEL_BOUNDS[TraitLevel.MEDIUM]) == 2
    assert all(
        len(LEVEL_BOUNDS[level]) == 1
        for level in TraitLevel
        if level is not TraitLevel.MEDIUM
    )


@pytest.mark.parametrize(
    ("age", "band"),
    [
        (18, "16-19"),  # our floor is 18; μ's youngest band is 16-19
        (19, "16-19"),
        (20, "20-29"),
        (29, "20-29"),
        (30, "30-39"),
        (45, "40-49"),
        (79, "70-79"),
        (80, "80+"),
        (100, "80+"),
    ],
)
def test_mu_band(age, band):
    assert _mu_band(age) == band


def test_mu_covers_every_band_and_gender():
    assert set(MU) == {f"{b}|{g}" for b in AGE_BANDS for g in ("female", "male")}
    assert all(len(vec) == len(TRAIT_ORDER) for vec in MU.values())


def test_sigma_is_a_valid_covariance():
    sigma = np.array(SIGMA)
    assert sigma.shape == (5, 5)
    assert np.allclose(sigma, sigma.T)  # symmetric
    assert np.allclose(np.diag(sigma), 1.0)  # unit diagonal in z-space
    assert np.all(np.linalg.eigvalsh(sigma) > 0)  # positive-definite → valid MVN


def test_sample_big_five_is_deterministic_for_a_seed():
    a = sample_big_five(30, "male", np.random.default_rng(42))
    b = sample_big_five(30, "male", np.random.default_rng(42))
    assert a == b


def test_sample_big_five_recovers_mu_and_sigma():
    rng = np.random.default_rng(0)
    draws = np.array(
        [[s for _, s in sample_big_five(25, "male", rng)] for _ in range(8000)]
    )
    # age 25 → band 20-29; the draw's mean recovers μ and its correlations Σ
    assert np.allclose(draws.mean(axis=0), MU["20-29|male"], atol=0.05)
    assert np.allclose(np.corrcoef(draws, rowvar=False), SIGMA, atol=0.05)
