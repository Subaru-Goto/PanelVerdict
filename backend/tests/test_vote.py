from typing import Literal

import pytest

from app.schemas import BigFive, PanelVoteOutput, Persona
from app.vote import collect_panel_votes, resolve_choice


class StubLLM:
    """A PanelLLM that returns the same canned vote for every call."""

    def __init__(self, chosen: Literal["option_1", "option_2"], reason: str = "stub"):
        self._chosen = chosen
        self._reason = reason

    def vote(
        self, *, system_prompt: str, option_1: str, option_2: str
    ) -> PanelVoteOutput:
        return PanelVoteOutput(chosen=self._chosen, reason=self._reason)


def _persona(pid: str) -> Persona:
    """Valid persona with filler traits — only the id matters to these tests."""
    return Persona(
        id=pid,
        age=30,
        gender="male",
        region="X",
        income="middle",
        education="X",
        interests=["x"],
        big_five=BigFive(
            openness="low",
            conscientiousness="low",
            extraversion="low",
            agreeableness="low",
            neuroticism="low",
        ),
    )


@pytest.mark.parametrize(
    ("chosen", "presentation_order", "expected"),
    [
        # Same order shown: option_1 is first, option_2 is second.
        ("option_1", ["vA", "vB"], "vA"),
        ("option_2", ["vA", "vB"], "vB"),
        # Swapped order (the case counterbalancing creates): the SLOT still
        # maps by position, so option_1 now refers to vB.
        ("option_1", ["vB", "vA"], "vB"),
        ("option_2", ["vB", "vA"], "vA"),
    ],
)
def test_resolve_choice(
    chosen: Literal["option_1", "option_2"],
    presentation_order: list[str],
    expected: str,
) -> None:
    assert resolve_choice(chosen, presentation_order) == expected


def test_collect_panel_votes_single_persona_builds_record() -> None:
    variants = {"vA": "Save 50% today", "vB": "Limited time: half price"}
    records = collect_panel_votes(
        test_id="t1",
        variants=variants,
        panel=[_persona("p1")],
        llm=StubLLM(chosen="option_1"),
    )

    assert len(records) == 1
    record = records[0]
    assert record.persona_id == "p1"
    assert record.test_id == "t1"
    assert record.presentation_order == ["vA", "vB"]
    assert record.chosen_variant_id == "vA"  # option_1 -> first shown = vA
    assert record.reason == "stub"


def test_collect_panel_votes_counterbalances_order_by_index() -> None:
    variants = {"vA": "Save 50% today", "vB": "Limited time: half price"}
    records = collect_panel_votes(
        test_id="t1",
        variants=variants,
        panel=[_persona("p1"), _persona("p2")],
        llm=StubLLM(chosen="option_1"),
    )

    # Constant vote ("option_1"), so any difference is the order alternating:
    # even index sees [vA, vB], odd index sees [vB, vA].
    assert records[0].presentation_order == ["vA", "vB"]
    assert records[0].chosen_variant_id == "vA"
    assert records[1].presentation_order == ["vB", "vA"]
    assert records[1].chosen_variant_id == "vB"


@pytest.mark.parametrize(
    "variants",
    [
        {"vA": "only one"},
        {"vA": "a", "vB": "b", "vC": "c"},
    ],
)
def test_collect_panel_votes_requires_exactly_two_variants(
    variants: dict[str, str],
) -> None:
    # Empty panel: the check must fire up front, independent of the loop.
    with pytest.raises(ValueError, match="exactly 2 variants"):
        collect_panel_votes(
            test_id="t1",
            variants=variants,
            panel=[],
            llm=StubLLM(chosen="option_1"),
        )
