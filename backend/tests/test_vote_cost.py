import argparse
from pathlib import Path

import pytest

from app.vote import VoteUsage
from experiments.vote_cost import CostRow, _effort, _read, _rows, _write


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

    assert [(row.persona_id, row.usage and row.usage.input_tokens) for row in rows] == [
        ("p1", 301),
        ("p2", 302),
        ("p3", 303),
    ]


def test_a_vote_that_reported_no_usage_keeps_its_row_and_holds_no_usage() -> None:
    """The vote happened, so it gets a row. Substituting zeros would pull every mean the
    report computes toward a cost nobody was charged."""
    rows = _rows(None, 1, ["p1", "p2"], (_usage(300), None))

    assert rows[1].persona_id == "p2"
    assert rows[1].usage is None


def test_a_written_run_reads_back_identical(tmp_path: Path) -> None:
    """`--report` re-reads a run rather than re-paying for it, so the round trip is the
    only thing standing between a recorded measurement and a lost one. The optional
    fields are the ones at risk: a None that returns as 0 would be a silent correction."""
    rows = [
        CostRow(arm="low", replicate=0, persona_id="p1", usage=_usage(301)),
        CostRow(
            arm="low",
            replicate=0,
            persona_id="p2",
            usage=VoteUsage(
                input_tokens=302,
                cached_tokens=None,
                output_tokens=80,
                reasoning_tokens=None,
                cost=None,
                seconds=4.0,
            ),
        ),
        CostRow(
            arm="low",
            replicate=0,
            persona_id="p3",
            usage=None,
            error="OutputParserException",
        ),
    ]
    path = tmp_path / "cost.jsonl"

    _write(rows, path)

    assert _read(path) == rows


def test_an_unknown_effort_is_refused_before_anything_is_paid_for() -> None:
    """An effort the provider does not recognise is accepted by the request and then does
    nothing, so a typo would return the default's numbers under the wrong arm label."""
    with pytest.raises(argparse.ArgumentTypeError):
        _effort("lo")


def test_every_effort_the_type_admits_is_selectable_from_the_command_line() -> None:
    """The CLI reads its vocabulary off `ReasoningEffort` rather than repeating it, so a
    level added to the type cannot end up rejected by the only thing that can select it."""
    assert _effort("default") is None
    assert [_effort(name) for name in ("none", "minimal", "low", "max")] == [
        "none",
        "minimal",
        "low",
        "max",
    ]
