import argparse

import pytest

from app.vote import VoteUsage
from experiments.vote_cost import _effort, _rows


def _usage(input_tokens: int) -> VoteUsage:
    return VoteUsage(
        input_tokens=input_tokens,
        cached_tokens=0,
        output_tokens=80,
        reasoning_tokens=192,
        cost=0.0002,
        seconds=4.0,
    )


def test_each_row_carries_the_usage_of_the_panelist_it_names() -> None:
    """The rows are what the cost reading is computed from, so a usage figure attached to
    the wrong persona id would produce a plausible mean over a mislabelled panel."""
    rows = _rows("low", 0, ["p1", "p2", "p3"], (_usage(301), _usage(302), _usage(303)))

    assert [(row.persona_id, row.input_tokens) for row in rows] == [
        ("p1", 301),
        ("p2", 302),
        ("p3", 303),
    ]


def test_a_vote_without_usage_becomes_a_row_of_nulls_not_zeros() -> None:
    """A zero would enter a mean and pull it down; a null is excluded from it. The vote
    still gets a row, because it happened."""
    rows = _rows("default", 1, ["p1", "p2"], (_usage(300), None))

    assert rows[1].persona_id == "p2"
    assert rows[1].input_tokens is None
    assert rows[1].cost is None


def test_an_unknown_effort_is_refused_before_anything_is_paid_for() -> None:
    """An effort the provider does not recognise is accepted by the request and then does
    nothing, so a typo would return the default's numbers under the wrong arm label."""
    with pytest.raises(argparse.ArgumentTypeError):
        _effort("lo")


def test_default_names_the_absence_of_a_reasoning_parameter() -> None:
    assert _effort("default") is None
    assert _effort("low") == "low"
