from collections import Counter
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

Axis = Literal["country", "age_band", "gender", "education"]

# Marginals audited separately (D3): joint cells are too sparse at 5k to estimate
# concentration — a known limitation is missing interaction stereotypes.
AXES: tuple[Axis, ...] = ("country", "age_band", "gender", "education")


@dataclass(frozen=True)
class InterestObservation:
    """One (persona, interest) pair with its demographic group keys."""

    persona_id: str
    country: str
    age_band: str
    gender: str
    education: str
    interest: str


@dataclass(frozen=True, eq=False)
class Pool:
    """The generated pool the audit measures."""

    observations: list[InterestObservation]
    vectors: FloatArray

    def __post_init__(self) -> None:
        if len(self.observations) != len(self.vectors):
            raise ValueError(
                f"{len(self.observations)} observations but {len(self.vectors)} vectors"
            )

    @cached_property
    def prepared(self) -> FloatArray:
        return prepare(self.vectors)


@dataclass(frozen=True)
class GroupDispersion:
    group: str
    size: int
    dispersion: float


@dataclass(frozen=True)
class AxisReport:
    axis: Axis
    pool_dispersion: float
    groups: list[GroupDispersion]


@dataclass(frozen=True)
class CollapseFlag:
    axis: Axis
    group: str
    dispersion: float
    size: int
    exemplars: list[str]
    persona_ids: list[str]


def _unit(vectors: FloatArray) -> FloatArray:
    """L2-normalize each row; leave any zero-length row unchanged."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0.0, 1.0, norms)


def prepare(vectors: FloatArray) -> FloatArray:
    """Unit-normalize, mean-center (decone anisotropy), re-normalize.

    Embeddings sit in a narrow cone, which inflates every cosine similarity;
    subtracting the pool mean restores discriminability (the "all-but-the-top"
    intuition, mean term only).
    """
    units = _unit(vectors)
    return _unit(units - units.mean(axis=0))


def dispersion(unit_vectors: FloatArray) -> float:
    """1 − mean-resultant-length: 0 = all identical (collapsed) → 1 = spread.

    Expects L2-normalized rows. `‖mean(unit)‖` is the directional-statistics
    measure of how aligned a set of directions is.
    """
    if len(unit_vectors) == 0:
        return 0.0
    return float(1.0 - np.linalg.norm(unit_vectors.mean(axis=0)))


def _group_indices(
    observations: list[InterestObservation], axis: Axis
) -> dict[str, list[int]]:
    # Axis's literal values must equal InterestObservation field names — getattr
    # binds them, so renaming a field means updating the Literal in lockstep.
    groups: dict[str, list[int]] = {}
    for i, obs in enumerate(observations):
        groups.setdefault(getattr(obs, axis), []).append(i)
    return groups


def audit_axis(pool: Pool, axis: Axis) -> AxisReport:
    """Dispersion of each group on `axis`, plus the pool baseline.

    Preparation is pool-wide (the anisotropy fix uses the whole pool's mean);
    collapse is then read per group. A group far below the pool dispersion has
    collapsed onto a caricature.
    """
    prepared = pool.prepared
    groups = [
        GroupDispersion(value, len(idx), dispersion(prepared[idx]))
        for value, idx in _group_indices(pool.observations, axis).items()
    ]
    return AxisReport(axis, dispersion(prepared), groups)


def audit_pool(pool: Pool) -> dict[Axis, AxisReport]:
    """Every marginal's report, sharing the pool's one-time preparation."""
    return {axis: audit_axis(pool, axis) for axis in AXES}


def flag_collapsed(
    pool: Pool,
    axis: Axis,
    *,
    threshold: float,
    min_group_size: int,
    n_exemplars: int = 3,
) -> list[CollapseFlag]:
    """Groups whose dispersion is below `threshold` — the sparing-regen worklist.

    Skips groups smaller than `min_group_size` (dispersion is noise on a handful
    of interests). Names culprit interests by frequency and returns the
    persona_ids holding them, for targeted regeneration in 006f. `threshold` is
    tuned on the first real pool, not baked in.
    """
    prepared = pool.prepared
    flags: list[CollapseFlag] = []
    for value, idx in _group_indices(pool.observations, axis).items():
        if len(idx) < min_group_size:
            continue
        group_dispersion = dispersion(prepared[idx])
        if group_dispersion >= threshold:
            continue
        group = [pool.observations[i] for i in idx]
        counts = Counter(obs.interest for obs in group)
        exemplars = [interest for interest, _ in counts.most_common(n_exemplars)]
        chosen = set(exemplars)
        persona_ids = sorted(
            {obs.persona_id for obs in group if obs.interest in chosen}
        )
        flags.append(
            CollapseFlag(
                axis=axis,
                group=value,
                dispersion=group_dispersion,
                size=len(idx),
                exemplars=exemplars,
                persona_ids=persona_ids,
            )
        )
    return flags
