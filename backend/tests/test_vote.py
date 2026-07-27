import threading
import time
from typing import Literal

import pytest

from app.bigfive import bigfive_from_levels
from app.schemas import PanelVoteOutput, Persona, TraitLevel
from app.vote import collect_panel_votes, presentation_orders, resolve_choice


def _persona(pid: str, *, age: int = 30) -> Persona:
    """Valid persona with filler traits — only the id and age matter to these tests."""
    return Persona(
        id=pid,
        country="US",
        age=age,
        gender="male",
        income_quintile=3,
        education="secondary",
        big_five=bigfive_from_levels(
            openness=TraitLevel.LOW,
            conscientiousness=TraitLevel.LOW,
            extraversion=TraitLevel.LOW,
            agreeableness=TraitLevel.LOW,
            neuroticism=TraitLevel.LOW,
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


_VARIANTS = ("vA", "vB")
_FORWARD = ["vA", "vB"]
_REVERSED = ["vB", "vA"]


@pytest.mark.parametrize("count", [1, 2, 3, 7, 200, 201])
def test_every_panelist_gets_one_order_of_both_variants(count: int) -> None:
    orders = presentation_orders(_VARIANTS, count, seed=0)

    assert len(orders) == count
    assert all(order in (_FORWARD, _REVERSED) for order in orders)


@pytest.mark.parametrize("count", [2, 8, 200])
def test_an_even_panel_is_split_exactly_in_half(count: int) -> None:
    """What counterbalancing means. gpt-5-mini picks the first-shown option 0.66 of
    the time (014, 5,400 votes), so an imbalance here moves the top line directly —
    it is a bias in the measurement, not noise that averages out."""
    orders = presentation_orders(_VARIANTS, count, seed=0)

    assert orders.count(_FORWARD) == count // 2


@pytest.mark.parametrize("count", [1, 3, 7, 201])
def test_an_odd_panel_is_off_by_exactly_one(count: int) -> None:
    """The closest a whole number of votes can get, rather than a drift that grows."""
    forward = presentation_orders(_VARIANTS, count, seed=0).count(_FORWARD)

    assert abs(forward - (count - forward)) == 1


def test_the_same_seed_assigns_the_same_orders() -> None:
    """`presentation_order` is stored per vote and the panel is reproducible, so the
    pairing has to be too — otherwise a re-run is not the same test."""
    assert presentation_orders(_VARIANTS, 50, seed=7) == presentation_orders(
        _VARIANTS, 50, seed=7
    )


def test_a_different_seed_pairs_panelists_with_different_positions() -> None:
    assert presentation_orders(_VARIANTS, 50, seed=1) != presentation_orders(
        _VARIANTS, 50, seed=2
    )


def test_the_assignment_does_not_track_the_panel_s_own_order() -> None:
    """Alternating on index is exactly balanced and still wrong: it ties who-sees-what
    to however the panel arrived, and callers control that — `load_pool` returns id
    order, which groups by country. Shuffling breaks the coupling, and adjacent
    panelists sharing an order is the visible sign that it is broken."""
    orders = presentation_orders(_VARIANTS, 200, seed=0)

    assert any(first == second for first, second in zip(orders, orders[1:]))


def test_collect_panel_votes_single_persona_builds_record(stub_llm) -> None:
    variants = {"vA": "Save 50% today", "vB": "Limited time: half price"}
    votes = collect_panel_votes(
        test_id="t1",
        variants=variants,
        panel=[_persona("p1")],
        llm=stub_llm(chosen="option_1"),
    )

    assert len(votes.records) == 1
    record = votes.records[0]
    assert record.persona_id == "p1"
    assert record.test_id == "t1"
    assert record.presentation_order == ["vA", "vB"]
    assert record.chosen_variant_id == "vA"  # option_1 -> first shown = vA
    assert record.reason == "stub"


def test_the_panel_s_orders_are_counterbalanced(stub_llm) -> None:
    """The vote is constant ("option_1"), so the winner is decided entirely by which
    order each panelist saw — a balanced split has to come out 50/50."""
    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "Save 50% today", "vB": "Limited time: half price"},
        panel=[_persona(f"p{i}") for i in range(20)],
        llm=stub_llm(chosen="option_1"),
    )

    chosen = [record.chosen_variant_id for record in votes.records]
    assert chosen.count("vA") == chosen.count("vB") == 10


def _aged_panel(count: int) -> list[Persona]:
    """One panelist per distinct age, so a stub can tell from the prompt who it is
    serving — the persona id is deliberately not in the prompt."""
    return [_persona(f"p{i}", age=30 + i) for i in range(count)]


class FailingOnAge:
    """Refuses one panelist and answers the rest, like a model returning nothing
    parseable for one prompt out of two hundred."""

    def __init__(self, age: int) -> None:
        self._age = age

    def vote(
        self, *, system_prompt: str, option_1: str, option_2: str
    ) -> PanelVoteOutput:
        if f"{self._age}-year-old" in system_prompt:
            raise RuntimeError("no structured vote")
        return PanelVoteOutput(chosen="option_1", reason="stub")


def test_a_failed_vote_costs_that_panelist_and_no_other() -> None:
    """A panel is 200 requests over a network; one failing must not throw away the
    other 199. The shortfall is reported rather than raised, because whether a thin
    panel still deserves a verdict is the caller's call, not the mechanism's."""
    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "a", "vB": "b"},
        panel=_aged_panel(5),
        llm=FailingOnAge(33),
    )

    assert [r.persona_id for r in votes.records] == ["p0", "p1", "p2", "p4"]
    assert [f.persona_id for f in votes.failures] == ["p3"]
    assert "no structured vote" in votes.failures[0].error


def test_the_votes_are_cast_concurrently() -> None:
    """200 serial round trips at a few seconds each is ten minutes of waiting. The
    barrier is the assertion: every vote has to be in flight at once for any of them to
    return, so a serial implementation cannot reach the end of this test."""
    panel = [_persona(f"p{i}") for i in range(4)]
    barrier = threading.Barrier(len(panel))

    class Rendezvous:
        def vote(self, *, system_prompt, option_1, option_2):
            barrier.wait(timeout=5)
            return PanelVoteOutput(chosen="option_1", reason="stub")

    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "a", "vB": "b"},
        panel=panel,
        llm=Rendezvous(),
        concurrency=len(panel),
    )

    assert len(votes.records) == len(panel)


class AnsweringYoungestLast:
    """Finishes in reverse panel order, so the records cannot have been appended as
    the votes arrived."""

    def vote(
        self, *, system_prompt: str, option_1: str, option_2: str
    ) -> PanelVoteOutput:
        age = int(system_prompt.split("-year-old")[0].rsplit(" ", 1)[1])
        time.sleep(0.02 * (40 - age))
        return PanelVoteOutput(chosen="option_1", reason="stub")


def test_the_records_follow_the_panel_not_the_finishing_order() -> None:
    """Concurrency must not reach the output. Whoever answers first, the records come
    back in panel order, so two runs of one test produce comparable lists."""
    panel = _aged_panel(6)

    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "a", "vB": "b"},
        panel=panel,
        llm=AnsweringYoungestLast(),
        concurrency=len(panel),
    )

    assert [r.persona_id for r in votes.records] == [f"p{i}" for i in range(6)]


@pytest.mark.parametrize(
    "variants",
    [
        {"vA": "only one"},
        {"vA": "a", "vB": "b", "vC": "c"},
    ],
)
def test_collect_panel_votes_requires_exactly_two_variants(
    variants: dict[str, str], stub_llm
) -> None:
    # Empty panel: the check must fire up front, independent of the loop.
    with pytest.raises(ValueError, match="exactly 2 variants"):
        collect_panel_votes(
            test_id="t1",
            variants=variants,
            panel=[],
            llm=stub_llm(chosen="option_1"),
        )
