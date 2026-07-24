import numpy as np
import pytest

from app.stereotype_audit import (
    AXES,
    InterestObservation,
    Pool,
    _unit,
    audit_axis,
    audit_pool,
    dispersion,
    flag_collapsed,
    prepare,
)


# --- seam 1: dispersion of a set of directions ---


def test_dispersion_is_zero_for_identical_directions() -> None:
    vectors = _unit(np.array([[1.0, 0.0, 0.0]] * 5))
    assert dispersion(vectors) == 0.0


def test_dispersion_is_one_for_opposing_directions() -> None:
    vectors = np.array([[1.0, 0.0], [-1.0, 0.0]])
    assert dispersion(vectors) == 1.0


def test_dispersion_orders_tight_below_spread() -> None:
    tight = _unit(np.array([[1.0, 0.02, 0.0], [1.0, 0.0, 0.02], [1.0, 0.0, 0.0]]))
    spread = _unit(np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]))
    assert dispersion(tight) < dispersion(spread)


# --- seam 2: preprocessing ---


def test_prepare_returns_unit_rows() -> None:
    rng = np.random.default_rng(0)
    prepared = prepare(rng.normal(size=(10, 8)))
    assert np.allclose(np.linalg.norm(prepared, axis=1), 1.0)


# --- the pool aggregate ---


def test_pool_rejects_misaligned_observations_and_vectors() -> None:
    obs = [InterestObservation("p1", "US", "30-39", "male", "tertiary", "fitness")]
    with pytest.raises(ValueError, match="observations"):
        Pool(observations=obs, vectors=np.zeros((2, 4)))


def _two_group_pool() -> Pool:
    """US collapsed onto one direction ("fitness"); JP spread across many."""
    rng = np.random.default_rng(1)
    observations: list[InterestObservation] = []
    vectors: list[np.ndarray] = []
    base = np.array([1.0, 0.0, 0.0, 0.0])
    for i in range(20):
        observations.append(
            InterestObservation(f"us{i}", "US", "30-39", "male", "tertiary", "fitness")
        )
        vectors.append(base + rng.normal(scale=0.01, size=4))
    for i in range(20):
        observations.append(
            InterestObservation(
                f"jp{i}", "JP", "30-39", "male", "tertiary", f"hobby{i}"
            )
        )
        vectors.append(rng.normal(size=4))
    return Pool(observations=observations, vectors=np.array(vectors))


# --- seams 3+4: grouping + per-axis report ---


def test_audit_axis_buckets_by_group_and_finds_the_collapse() -> None:
    report = audit_axis(_two_group_pool(), "country")

    by_group = {g.group: g for g in report.groups}
    assert by_group["US"].size == 20 and by_group["JP"].size == 20
    # the collapsed group bunches tightly → lower dispersion than the varied one
    assert by_group["US"].dispersion < by_group["JP"].dispersion


def test_audit_pool_reports_every_marginal() -> None:
    reports = audit_pool(_two_group_pool())
    assert set(reports) == set(AXES)


# --- seam 5: flagging collapsed groups ---


def test_flag_collapsed_flags_only_the_collapsed_group_with_culprits() -> None:
    pool = _two_group_pool()
    by_group = {g.group: g.dispersion for g in audit_axis(pool, "country").groups}
    threshold = (by_group["US"] + by_group["JP"]) / 2  # cut between the two

    flags = flag_collapsed(pool, "country", threshold=threshold, min_group_size=5)

    assert [f.group for f in flags] == ["US"]
    assert flags[0].exemplars == ["fitness"]  # the culprit interest, named
    assert all(pid.startswith("us") for pid in flags[0].persona_ids)


def test_flag_collapsed_skips_groups_below_min_size() -> None:
    # threshold that would flag everything, but no group meets the size floor
    flags = flag_collapsed(
        _two_group_pool(), "country", threshold=1.0, min_group_size=1000
    )
    assert flags == []
