import threading
from typing import Literal

import pytest

from app.bigfive import bigfive_from_levels
from app.panel import render_persona_prompt
from app.schemas import PanelVoteOutput, Persona, TraitLevel
from app.vote import (
    VoteResponse,
    VoteUsage,
    build_vote_request,
    collect_panel_votes,
    presentation_orders,
    resolve_choice,
    total_usage,
    vote_fingerprint,
)
from tests.factories import voted


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


def test_the_odd_panelist_out_does_not_always_favour_the_same_variant() -> None:
    """An odd panel cannot split evenly, so somebody breaks the tie. Handing the surplus
    to a fixed side would tilt every odd-sized panel toward the same variant, and at a
    0.66 first-position rate that is a repeatable bias rather than a rounding artefact —
    the same defect as index parity, one vote wide."""
    surplus = {
        (
            "forward"
            if presentation_orders(_VARIANTS, 7, seed=seed).count(_FORWARD) == 4
            else "reverse"
        )
        for seed in range(20)
    }

    assert surplus == {"forward", "reverse"}


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
    """Adjacent panelists sharing an order is the observable difference from index
    parity, which alternates by construction however the panel was sorted."""
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
    # Which order a lone panelist sees is the seed's to choose, so what is pinned is
    # that the positional vote was resolved against the order actually shown.
    assert record.presentation_order in (_FORWARD, _REVERSED)
    assert record.chosen_variant_id == record.presentation_order[0]
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

    configuration = "stub"

    def __init__(self, age: int) -> None:
        self._age = age

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        if f"{self._age}-year-old" in system_prompt:
            raise RuntimeError("no structured vote")
        return voted()


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
    barrier is the assertion: no vote returns until every vote is in flight, so under a
    serial implementation each one times out and the panel comes back empty."""
    panel = [_persona(f"p{i}") for i in range(4)]
    barrier = threading.Barrier(len(panel))

    class Rendezvous:
        configuration = "stub"

        def vote(
            self, *, system_prompt: str, option_1: str, option_2: str
        ) -> VoteResponse:
            barrier.wait(timeout=5)
            return voted()

    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "a", "vB": "b"},
        panel=panel,
        llm=Rendezvous(),
        concurrency=len(panel),
    )

    assert len(votes.records) == len(panel)


class EchoingThePrompt:
    """Answers with the prompt it was given, so a record can be checked against the
    panelist it belongs to."""

    configuration = "stub"

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        return voted(reason=system_prompt)


def test_every_record_carries_the_vote_its_own_panelist_cast() -> None:
    """The failure concurrency invites: results collected as they arrive, then zipped
    back onto the panel, so every record is real and some belong to the wrong person.
    Nothing downstream could detect it — the reasons would be plausible and the tally
    unchanged — so the pairing is checked rather than the ordering it comes from."""
    panel = _aged_panel(6)

    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "a", "vB": "b"},
        panel=panel,
        llm=EchoingThePrompt(),
        concurrency=len(panel),
    )

    assert [r.persona_id for r in votes.records] == [f"p{i}" for i in range(6)]
    for record, persona in zip(votes.records, panel):
        assert record.reason == render_persona_prompt(persona)


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


class ReportingItsOwnAge:
    """Reports usage whose token count is the age in the prompt it was handed, so a
    usage figure can be traced back to the panelist it was billed for."""

    def __init__(self, refuse_age: int | None = None) -> None:
        self._refuse_age = refuse_age

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        age = int(system_prompt.split("-year-old")[0].split()[-1])
        if age == self._refuse_age:
            raise RuntimeError("no structured vote")
        return VoteResponse(
            output=PanelVoteOutput(chosen="option_1", reason="stub"),
            usage=VoteUsage(
                input_tokens=age,
                cached_tokens=None,
                output_tokens=1,
                reasoning_tokens=None,
                cost=None,
                seconds=0.0,
            ),
        )


def test_each_usage_figure_stays_with_the_vote_it_was_billed_for() -> None:
    """The same defect the presentation order has: usage collected as it arrives and
    zipped back onto the panel gives every record a real cost that belongs to someone
    else. The totals would be identical, so nothing downstream could notice — only the
    pairing can."""
    panel = _aged_panel(6)

    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "a", "vB": "b"},
        panel=panel,
        llm=ReportingItsOwnAge(),
        concurrency=len(panel),
    )

    ages = {p.id: p.age for p in panel}
    assert [u.input_tokens for u in votes.usage] == [
        ages[r.persona_id] for r in votes.records
    ]


def test_a_failed_vote_leaves_no_usage_hole_to_shift_the_rest() -> None:
    """A refused panelist is absent from `records`, so it must be absent from `usage`
    too. Keeping a placeholder would offset every figure after it by one and bill the
    wrong panelist for the rest of the panel."""
    panel = _aged_panel(5)

    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "a", "vB": "b"},
        panel=panel,
        llm=ReportingItsOwnAge(refuse_age=33),
    )

    assert len(votes.failures) == 1
    assert len(votes.usage) == len(votes.records) == 4
    assert [u.input_tokens for u in votes.usage] == [30, 31, 32, 34]


def test_totals_report_how_many_votes_each_sum_covers() -> None:
    """A sum over the votes that reported a field is a partial figure. Reporting it
    without its count is how a run gets planned against a number that is quietly too
    small — and reasoning is both the largest term and the one most likely to be
    missing."""
    usage = [
        VoteUsage(
            input_tokens=300,
            cached_tokens=0,
            output_tokens=80,
            reasoning_tokens=192,
            cost=0.001,
            seconds=1.0,
        ),
        VoteUsage(
            input_tokens=310,
            cached_tokens=None,
            output_tokens=90,
            reasoning_tokens=None,
            cost=None,
            seconds=2.0,
        ),
        None,
    ]

    totals = total_usage(usage)

    assert totals.votes == 3
    assert totals.usage_reported == 2
    assert totals.input_tokens == 610
    # One vote reported no cache figure at all; the other reported a real zero. A total
    # of 0 over one vote and a total of 0 over two are different claims.
    assert (totals.cached_tokens, totals.cached_reported) == (0, 1)
    assert totals.output_tokens == 170
    assert totals.reasoning_tokens == 192
    assert totals.reasoning_reported == 1
    assert totals.cost == 0.001
    assert totals.cost_reported == 1
    # A wave costs its slowest member, so the slowest vote is the one number
    # that explains a run's wall time; the sum next to it says how much of that
    # was concurrent. Both were measured per vote long before anything summed them.
    assert totals.seconds_slowest == 2.0
    assert totals.seconds_total == 3.0


def test_totals_of_a_run_that_reported_nothing_are_zero_not_absent() -> None:
    totals = total_usage([None, None])

    assert totals.votes == 2
    assert totals.usage_reported == 0
    assert totals.reasoning_tokens == 0
    assert totals.cost == 0.0
    # Every vote was a cache hit: no model was waited on, so the honest slowest
    # is zero rather than an absence to be explained.
    assert totals.seconds_slowest == 0.0


class TestVoteFingerprint:
    """The cache key is the question itself: any change to what the model
    would be asked must change the fingerprint, or a stored vote silently answers a
    question it was never asked. The ingredients are the exact request strings plus
    the adapter's configuration — not persona/test ids, which can stay equal across
    a prompt change."""

    def _key(
        self,
        *,
        persona: Persona | None = None,
        order: list[str] | None = None,
        variants: dict[str, str] | None = None,
        configuration: str = "model=openai/gpt-5-mini",
    ) -> str:
        return vote_fingerprint(
            build_vote_request(
                persona or _persona("p0"),
                order or ["vA", "vB"],
                variants=variants
                or {"vA": "Save 50% today", "vB": "Members save half"},
            ),
            configuration=configuration,
        )

    def test_the_same_question_keys_the_same(self) -> None:
        assert self._key() == self._key()

    def test_every_ingredient_of_the_question_changes_the_key(self) -> None:
        keys = [
            self._key(),
            self._key(configuration="model=openai/gpt-6"),
            # A different age renders a different persona prompt; the id alone would
            # not, since the prompt deliberately omits it.
            self._key(persona=_persona("p0", age=55)),
            self._key(variants={"vA": "Save 50% today!", "vB": "Members save half"}),
            self._key(order=["vB", "vA"]),
        ]

        assert len(set(keys)) == len(keys)


def test_the_request_shows_the_variants_in_presentation_order() -> None:
    """option_1 is whatever the order puts first — the position bias lives or
    dies on this mapping, so the request builder gets its own check."""
    request = build_vote_request(
        _persona("p0"),
        ["vB", "vA"],
        variants={"vA": "alpha text", "vB": "beta text"},
    )

    assert request.option_1 == "beta text"
    assert request.option_2 == "alpha text"
    assert "30-year-old" in request.system_prompt


def test_pre_assigned_orders_are_honoured() -> None:
    """Each chunk's orders are fixed before it is split into cache hits and
    misses, so the misses must arrive with their positions already assigned — a
    fresh draw over the smaller panel would re-pair panelists with positions and
    turn every would-be cache hit into a paid miss on the next run."""
    panel = [_persona("p0"), _persona("p1")]
    # Both reversed — a split no internal draw would produce, so honouring it is
    # only explicable by the parameter.
    orders = [["vB", "vA"], ["vB", "vA"]]

    votes = collect_panel_votes(
        test_id="t1",
        variants={"vA": "alpha", "vB": "beta"},
        panel=panel,
        llm=AlwaysFirstShown(),
        orders=orders,
    )

    assert [r.presentation_order for r in votes.records] == orders
    assert [r.chosen_variant_id for r in votes.records] == ["vB", "vB"]


class AlwaysFirstShown:
    configuration = "stub"

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        return voted("option_1")
