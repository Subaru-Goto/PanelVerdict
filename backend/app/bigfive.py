"""Big Five sampling: draw correlated (O,C,E,A,N) z-scores conditioned on age+gender.

Scores are the source of truth; `TraitLevel` is derived at render via `bucketize`.
Design + seed-data provenance: issues/006c, docs/research/persona-seed-data.md.
"""

import json
from pathlib import Path
from typing import Literal

import numpy as np

from app.schemas import BigFive, TraitLevel

# The empirical μ/Σ live in the loaded artifact — one home for the numbers,
# carrying their own provenance. Shared across all countries (001 decision (i):
# country does not condition the Big Five μ).
_NORMS = json.loads((Path(__file__).parent / "data" / "bigfive_norms.json").read_text())
MU: dict[str, list[float]] = _NORMS["mu"]
SIGMA: list[list[float]] = _NORMS["sigma"]
_SIGMA = np.array(SIGMA)


def sample_big_five(
    age: int, gender: Literal["male", "female"], rng: np.random.Generator
) -> BigFive:
    """Draw a correlated (O,C,E,A,N) z-score vector from MVN(μ(age,gender), Σ).

    `rng` is injected so the whole pool is reproducible from one master seed;
    scores are stored raw and bucketized only at render.
    """
    mean = MU[f"{_mu_band(age)}|{gender}"]
    openness, conscientiousness, extraversion, agreeableness, neuroticism = (
        rng.multivariate_normal(mean, _SIGMA)
    )
    return BigFive(
        openness=float(openness),
        conscientiousness=float(conscientiousness),
        extraversion=float(extraversion),
        agreeableness=float(agreeableness),
        neuroticism=float(neuroticism),
    )


# Standard-normal quantile cutoffs (006j D1b): +/-0.5 and +/-1.5 cut a normal
# population into 6.7 / 24.2 / 38.3 / 24.2 / 6.7. Derived from the distribution,
# not chosen — a conditioned cell skews off those shares.
_INNER_CUTOFF = 0.5
_OUTER_CUTOFF = 1.5


def _mu_band(age: int) -> str:
    """Map a concrete age to its μ age band (D&L bands; youngest is "16-19").

    Our 18 floor sits inside the 16-19 band, so 18-19 read μ there; ages from 20
    up fall in one decade band; 80+ is the open top band.
    """
    if age < 20:
        return "16-19"
    if age >= 80:
        return "80+"
    start = (age // 10) * 10
    return f"{start}-{start + 9}"


def bucketize(score: float) -> TraitLevel:
    """Map a sampled z-score to its trait level at render time.

    Boundaries belong to the inner band, so an exact -1.5 is LOW and an exact
    -0.5 is MEDIUM.
    """
    if score < -_OUTER_CUTOFF:
        return TraitLevel.VERY_LOW
    if score < -_INNER_CUTOFF:
        return TraitLevel.LOW
    if score <= _INNER_CUTOFF:
        return TraitLevel.MEDIUM
    if score <= _OUTER_CUTOFF:
        return TraitLevel.HIGH
    return TraitLevel.VERY_HIGH


# Representative z-score per level — a clearly-in-bucket value (bucketize inverts
# it). For hand-authored panels that think in levels, not sampled personas.
_LEVEL_SCORE: dict[TraitLevel, float] = {
    TraitLevel.VERY_LOW: -2.0,
    TraitLevel.LOW: -1.0,
    TraitLevel.MEDIUM: 0.0,
    TraitLevel.HIGH: 1.0,
    TraitLevel.VERY_HIGH: 2.0,
}


def bigfive_from_levels(
    *,
    openness: TraitLevel,
    conscientiousness: TraitLevel,
    extraversion: TraitLevel,
    agreeableness: TraitLevel,
    neuroticism: TraitLevel,
) -> BigFive:
    """Build a BigFive from trait levels, for hand-authored (non-sampled) panels."""
    return BigFive(
        openness=_LEVEL_SCORE[openness],
        conscientiousness=_LEVEL_SCORE[conscientiousness],
        extraversion=_LEVEL_SCORE[extraversion],
        agreeableness=_LEVEL_SCORE[agreeableness],
        neuroticism=_LEVEL_SCORE[neuroticism],
    )
