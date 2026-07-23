import numpy as np
import pytest

from app.bigfive import (
    _mu_band,
    bigfive_from_levels,
    bucketize,
    MU,
    sample_big_five,
    SIGMA,
)
from app.schemas import TRAIT_ORDER, TraitLevel
from pipeline.derive_bigfive_norms import AGE_BANDS


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (-2.0, TraitLevel.LOW),
        (-0.6, TraitLevel.LOW),
        (-0.5, TraitLevel.MEDIUM),  # boundary is MEDIUM (low <= z <= high)
        (0.0, TraitLevel.MEDIUM),
        (0.5, TraitLevel.MEDIUM),  # boundary is MEDIUM
        (0.6, TraitLevel.HIGH),
        (2.0, TraitLevel.HIGH),
    ],
)
def test_bucketize(score, level):
    assert bucketize(score) == level


def test_bigfive_from_levels_round_trips_through_bucketize():
    # the representative score for each level must bucketize back to that level,
    # i.e. _LEVEL_SCORE stays outside the ±0.5 cutoffs — locks that coupling
    for level in TraitLevel:
        bf = bigfive_from_levels(
            openness=level,
            conscientiousness=level,
            extraversion=level,
            agreeableness=level,
            neuroticism=level,
        )
        assert all(bucketize(score) == level for _, score in bf)


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
