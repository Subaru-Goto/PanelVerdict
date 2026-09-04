"""The evaluate run as a graph, with a human between selection and spending.

076/#166. What these tests defend is one property: **no panel is voted on whose
reading a human has not accepted** — and the corollary that the pause itself
costs nothing, because a gate that spends money before it asks is not a gate.
"""

import asyncio
import itertools
import threading

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from app import graph as graph_module
from app.graph import GateDecision, build_evaluate_graph
from app.schemas import Locale, TargetQuery
from app.roleplay import RolePlayRefused
from app.pipeline import EmptyPanel
from app.screening import ScreeningVerdict, UnsafeInput
from app.targeting import PANEL_SEED
from tests.factories import StubGenerator, seed_japanese

_VARIANTS = {"a": "Save 50% today", "b": "Limited time: half price"}


class CountingLLM:
    """A panel model that records every vote it is asked to cast."""

    configuration = "counting"

    def __init__(self) -> None:
        self.asked = 0
        self.enacted: list[str] = []

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ):
        from tests.factories import voted

        self.asked += 1
        self.enacted.append(enacted)
        return voted("option_1", "clear discount framing")


def _graph(aconn, *, llm=None, screener=None, saver=None, generator=None):
    return build_evaluate_graph(
        conn=aconn,
        llm=llm or CountingLLM(),
        screener=screener,
        generator=generator or StubGenerator(),
        checkpointer=saver or InMemorySaver(),
    )


def _japan_query() -> TargetQuery:
    """The settled reading the endpoint would seed for a JP-only run — the
    graph reads a done deal now, never a description (094)."""
    return TargetQuery(
        countries=(Locale.JP,),
        coverage="requested",
        min_age=18,
        max_age=100,
        gender=None,
        income_quintiles=(),
        education=(),
        traits=(),
        notices=(),
    )


def _start(**overrides) -> dict:
    return {
        "query": _japan_query(),
        "variants": _VARIANTS,
        "size": 5,
        # The paid path always has a verified subject by the time anything
        # votes (086/#177); these tests are that path.
        "owner": "acct-a",
    } | overrides


def _config(thread: str = "t-1") -> dict:
    return {"configurable": {"thread_id": thread}}


class ThreadNotingGenerator(StubGenerator):
    """Records which thread its blocking `draft` was called on."""

    def __init__(self) -> None:
        super().__init__()
        self.thread: str | None = None
        self.saw_a_running_loop: bool | None = None

    def draft(self, *, words: str):
        self.thread = threading.current_thread().name
        try:
            asyncio.get_running_loop()
            self.saw_a_running_loop = True
        except RuntimeError:
            self.saw_a_running_loop = False
        return super().draft(words=words)


@pytest.mark.anyio
async def test_the_sync_node_s_paid_call_never_reaches_the_event_loop(
    conn, aconn
) -> None:
    """`roleplay` is a sync `def` deliberately, and this is what makes that safe.

    LangGraph dispatches a sync node to a worker, so `generator.draft` — a paid
    model call over the network — is already off the loop, and wrapping it in
    `to_thread` would nest one thread inside another. That is a fact about
    LangGraph rather than about this code, which is exactly why it is asserted
    here instead of trusted: if an upgrade ever ran sync nodes inline, one
    caller's `draft` would stall every other request on the worker, and nothing
    else would catch it — `test_async_discipline` only inspects `async def`, and
    this node is not one.
    """
    seed_japanese(conn, 5)
    generator = ThreadNotingGenerator()

    # Non-blank audience words: blank means demographics only and drafts nothing.
    await _graph(aconn, generator=generator).ainvoke(
        _start(audience="Japanese homeowners"), _config()
    )

    assert generator.thread is not None, "the roleplay node never ran"
    assert generator.thread != threading.current_thread().name
    assert generator.saw_a_running_loop is False


@pytest.mark.anyio
async def test_the_run_stops_before_it_buys_anything(conn, aconn) -> None:
    """The gate's whole claim. A pause that has already spent is not a gate —
    it is a receipt."""
    seed_japanese(conn, 5)
    llm = CountingLLM()

    state = await _graph(aconn, llm=llm).ainvoke(_start(), _config())

    assert state["__interrupt__"], "the run should be waiting for a human"
    assert llm.asked == 0


@pytest.mark.anyio
async def test_the_pause_says_who_would_be_seated_and_what_it_would_cost(
    conn, aconn
) -> None:
    """A reader can only accept what they can see: the reading, the count, who
    it seats, and the price of finding out."""
    seed_japanese(conn, 5)

    state = await _graph(aconn).ainvoke(_start(), _config())

    preview = state["__interrupt__"][0].value
    assert preview["matched"] == 5
    assert preview["query"]["countries"] == ["JP"]
    assert preview["composition"]["countries"] == {"JP": 5}
    assert preview["estimated_usd"] > 0


@pytest.mark.anyio
async def test_accepting_buys_the_votes(conn, aconn) -> None:
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(aconn, llm=llm)
    await graph.ainvoke(_start(), _config())

    state = await graph.ainvoke(
        Command(resume=GateDecision(action="accept").model_dump()), _config()
    )

    assert llm.asked == 5
    assert state["result"].counts.voted == 5


@pytest.mark.anyio
async def test_adjusting_reseats_the_panel_without_paying_to_translate_again(
    conn, aconn
) -> None:
    """Editing the reading is free and deterministic — pure SQL. A second
    translation would be paid, non-reproducible, and could quietly disagree
    with the edit it was meant to apply."""
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(aconn, llm=llm)
    first = await graph.ainvoke(_start(), _config())
    edited = first["__interrupt__"][0].value["query"]

    state = await graph.ainvoke(
        Command(resume=GateDecision(action="adjust", query=edited).model_dump()),
        _config(),
    )

    # Re-seated and paused again, and no model of any kind was asked.
    assert state["__interrupt__"]
    assert llm.asked == 0


@pytest.mark.anyio
async def test_an_adjust_carries_edited_headlines_into_the_run(conn, aconn) -> None:
    """A mid-gate typo fix must reach the vote. The paused thread keeps the
    variants from the first submit, and resume updates graph state — that is
    what HITL resume is for — so the panel votes the text the reader sees on
    the form, not the one they already corrected (077, decided 2026-08-31)."""
    seed_japanese(conn, 5)
    graph = _graph(aconn)
    first = await graph.ainvoke(_start(), _config())
    kept = first["__interrupt__"][0].value["query"]
    fixed = {"a": "Save 50% this week", "b": "Members save half price this week"}

    state = await graph.ainvoke(
        Command(
            resume=GateDecision(
                action="adjust", query=kept, variants=fixed
            ).model_dump()
        ),
        _config(),
    )

    # Paused again — the edit is a new reading nobody accepted — and the
    # corrected text is what any later accept will vote on.
    assert state["__interrupt__"]
    assert state["variants"] == fixed


@pytest.mark.anyio
async def test_an_adjust_without_headlines_keeps_the_originals(conn, aconn) -> None:
    """Absence means untouched: an adjust that only re-seats must not blank
    the text the run is about."""
    seed_japanese(conn, 5)
    graph = _graph(aconn)
    first = await graph.ainvoke(_start(), _config())
    kept = first["__interrupt__"][0].value["query"]

    state = await graph.ainvoke(
        Command(resume=GateDecision(action="adjust", query=kept).model_dump()),
        _config(),
    )

    assert state["variants"] == _VARIANTS


@pytest.mark.anyio
async def test_an_adjustment_stops_again_rather_than_running_on(conn, aconn) -> None:
    """The edited reading is a new reading, and nobody has accepted it yet."""
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(aconn, llm=llm)
    first = await graph.ainvoke(_start(), _config())
    same = first["__interrupt__"][0].value["query"]

    state = await graph.ainvoke(
        Command(resume=GateDecision(action="adjust", query=same).model_dump()),
        _config(),
    )

    assert state["__interrupt__"]
    assert llm.asked == 0


@pytest.mark.anyio
async def test_an_audience_already_accepted_does_not_stop_again(conn, aconn) -> None:
    """The gate fires on the first run and whenever the audience changes — not
    on every run (077, amended). Iterating on headlines against a fixed
    audience would otherwise train the reader to dismiss an approval unread,
    which is weaker human-in-the-loop than one that fires when there is
    something to read."""
    seed_japanese(conn, 5)
    llm = CountingLLM()

    state = await _graph(aconn, llm=llm).ainvoke(
        _start(reading_accepted=True), _config("t-repeat")
    )

    assert "__interrupt__" not in state
    assert state["result"].counts.voted == 5


@pytest.mark.anyio
async def test_a_target_the_pool_cannot_serve_is_refused_before_the_gate(
    conn, aconn
) -> None:
    """Nothing to approve and nothing to spend: the refusal belongs where the
    panel is drawn, not after a human has been asked about an empty room."""
    seed_japanese(conn, 5)
    graph = _graph(aconn)
    conn.execute("DELETE FROM personas")
    conn.commit()

    with pytest.raises(EmptyPanel):
        await graph.ainvoke(_start(), _config())


@pytest.mark.anyio
async def test_refused_text_never_reaches_the_panel(conn, aconn) -> None:
    """The screener's one remaining post: the vote. Nothing before the gate is
    text a model reads (094) — the controls are SQL and the audience has its
    own classifier — so a flagged headline is refused where headlines are first
    shown to a model, before any vote is bought."""
    seed_japanese(conn, 5)
    llm = CountingLLM()

    class Refusing:
        def screen(self, text: str) -> ScreeningVerdict:
            return ScreeningVerdict(flagged=True, reason="prompt injection")

    graph = _graph(aconn, llm=llm, screener=Refusing())
    await graph.ainvoke(_start(), _config())

    with pytest.raises(UnsafeInput):
        await graph.ainvoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )
    assert llm.asked == 0


class CountingScreener:
    """A screener that records every text it was asked to check."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def screen(self, text: str) -> ScreeningVerdict:
        self.seen.append(text)
        return ScreeningVerdict(flagged=False, reason="")


@pytest.mark.anyio
async def test_a_preview_screens_nothing(conn, aconn) -> None:
    """No text a model reads exists before the gate any more: the controls are
    SQL, and the audience is guarded by the generator's classifier rather than
    the copy screener. A preview that paid for screening would be buying a
    check for a run that may never be accepted — and checking the wrong
    instrument's text at that."""
    seed_japanese(conn, 5)
    screener = CountingScreener()

    await _graph(aconn, screener=screener).ainvoke(_start(), _config())

    assert screener.seen == []


@pytest.mark.anyio
async def test_the_headlines_are_screened_before_they_reach_the_panel(
    conn, aconn
) -> None:
    """Deferred, never dropped: the vote is the step that shows a headline to a
    model, so the check has to land before it."""
    seed_japanese(conn, 5)
    screener = CountingScreener()
    graph = _graph(aconn, screener=screener)
    await graph.ainvoke(_start(), _config())

    await graph.ainvoke(
        Command(resume=GateDecision(action="accept").model_dump()), _config()
    )

    assert sorted(screener.seen) == sorted(_VARIANTS.values())


@pytest.mark.anyio
async def test_the_same_filter_seats_the_same_people(conn, aconn) -> None:
    """PANEL_SEED is fixed, so an unchanged audience is an unchanged panel —
    which is exactly why the gate can skip a repeat run without hiding
    anything."""
    seed_japanese(conn, 20)
    graph = _graph(aconn)

    first = (await graph.ainvoke(_start(), _config("t-a")))["__interrupt__"][0].value
    second = (await graph.ainvoke(_start(), _config("t-b")))["__interrupt__"][0].value

    assert PANEL_SEED == 0
    assert first["composition"] == second["composition"]


@pytest.mark.anyio
async def test_an_edit_that_matches_nobody_costs_a_click_not_the_run(
    conn, aconn
) -> None:
    """A human can edit the reading into an empty room, and must be able to
    edit their way back out of it.

    Raising here would be a trap rather than a refusal: the edit is already in
    state, so every later resume would re-run selection and fail the same way —
    the run unrecoverable, the money unspent but the work lost. The gate exists
    to invite exactly this experiment, so it has to survive it.
    """
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(aconn, llm=llm)
    first = await graph.ainvoke(_start(), _config("t-edit"))
    original = first["__interrupt__"][0].value["query"]
    nobody = original | {"min_age": 99, "max_age": 100}

    empty = await graph.ainvoke(
        Command(resume=GateDecision(action="adjust", query=nobody).model_dump()),
        _config("t-edit"),
    )
    back = await graph.ainvoke(
        Command(resume=GateDecision(action="adjust", query=original).model_dump()),
        _config("t-edit"),
    )
    done = await graph.ainvoke(
        Command(resume=GateDecision(action="accept").model_dump()), _config("t-edit")
    )

    assert empty["__interrupt__"][0].value["matched"] == 0
    assert (
        "Nobody in the pool matches"
        in empty["__interrupt__"][0].value["notices"][0]["message"]
    )
    assert back["__interrupt__"][0].value["matched"] == 5
    assert done["result"].counts.voted == 5
    assert llm.asked == 5


@pytest.mark.anyio
async def test_an_accept_with_nobody_seated_buys_nothing(conn, aconn) -> None:
    """The interface will not offer this, and the graph does not depend on the
    interface for it: a panel of zero has nobody to ask."""
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(aconn, llm=llm)
    first = await graph.ainvoke(_start(), _config("t-zero"))
    nobody = first["__interrupt__"][0].value["query"] | {"min_age": 99, "max_age": 100}
    await graph.ainvoke(
        Command(resume=GateDecision(action="adjust", query=nobody).model_dump()),
        _config("t-zero"),
    )

    state = await graph.ainvoke(
        Command(resume=GateDecision(action="accept").model_dump()), _config("t-zero")
    )

    assert llm.asked == 0
    assert state["__interrupt__"][0].value["matched"] == 0


@pytest.mark.anyio
async def test_a_paused_run_outlives_the_process_that_started_it(
    conn, aconn, pg_url
) -> None:
    """The gate's second requirement, after costing nothing: surviving a deploy.

    A pause that a restart forgets turns an approval into a lost run — worse
    than no gate, because the reader has already done the work of reading it.
    Two separate savers over the same database stand in for two processes: the
    second graph never saw the first one's selection, and resumes it anyway.

    This is also the test that proves the state is really serializable. An
    in-memory saver hands objects back unchanged and would pass whatever it was
    given; Postgres round-trips them through JSON.
    """
    seed_japanese(conn, 5)
    llm = CountingLLM()

    async with AsyncPostgresSaver.from_conn_string(pg_url) as before:
        await before.setup()
        paused = await _graph(aconn, llm=llm, saver=before).ainvoke(
            _start(), _config("t-restart")
        )

    async with AsyncPostgresSaver.from_conn_string(pg_url) as after:
        resumed = await _graph(aconn, llm=llm, saver=after).ainvoke(
            Command(resume=GateDecision(action="accept").model_dump()),
            _config("t-restart"),
        )

    assert paused["__interrupt__"][0].value["matched"] == 5
    assert resumed["result"].counts.voted == 5


@pytest.mark.anyio
async def test_what_a_restart_restores_is_the_panel_a_human_approved(
    conn, aconn, pg_url
) -> None:
    """Not the filter — the people.

    Re-selecting on resume would be a second query, and a second query is a
    second answer: the pool can change under a paused run (a reseed, a new
    country). Whoever the reader accepted is who votes, or the approval was
    about somebody else.
    """
    seed_japanese(conn, 5)

    async with AsyncPostgresSaver.from_conn_string(pg_url) as before:
        await before.setup()
        graph = _graph(aconn, saver=before)
        await graph.ainvoke(_start(), _config("t-pool-change"))
        seated = [
            p.id
            for p in (await graph.aget_state(_config("t-pool-change"))).values["panel"]
        ]

    conn.execute("DELETE FROM personas")
    conn.commit()

    async with AsyncPostgresSaver.from_conn_string(pg_url) as after:
        resumed = await _graph(aconn, saver=after).ainvoke(
            Command(resume=GateDecision(action="accept").model_dump()),
            _config("t-pool-change"),
        )

    assert len(seated) == 5
    assert resumed["result"].counts.voted == 5


@pytest.mark.anyio
async def test_a_second_run_of_the_same_test_replays_for_nothing(conn, aconn) -> None:
    """The replay guarantee, exercised through the graph rather than asserted.

    Votes are cached on the fingerprint of the exact question asked, so running
    the same headlines past the same panel a second time buys no model calls at
    all. The $0 demo depends on this, which is why the vote loop was moved into
    a node unedited.
    """
    seed_japanese(conn, 5)
    first_llm, second_llm = CountingLLM(), CountingLLM()

    first = await _graph(aconn, llm=first_llm).ainvoke(
        _start(reading_accepted=True), _config("t-paid")
    )
    second = await _graph(aconn, llm=second_llm).ainvoke(
        _start(reading_accepted=True), _config("t-replay")
    )

    assert first_llm.asked == 5
    assert second_llm.asked == 0
    assert second["result"].tally.counts == first["result"].tally.counts


class TestEnactedContext:
    """The audience words become one sentence a human approves, and that sentence
    is what every panelist is told. What the reader sees at the gate and what the
    panel receives must be the same string — that is the whole point of stopping.
    """

    @pytest.mark.anyio
    async def test_a_demographics_only_run_calls_no_generator(
        self, conn, aconn
    ) -> None:
        """Blank means demographics only, and the common case must stay free."""
        seed_japanese(conn, 5)
        generator = StubGenerator()

        await _graph(aconn, generator=generator).ainvoke(_start(), _config())

        assert generator.drafted == []

    @pytest.mark.anyio
    async def test_the_gate_shows_the_sentence_the_panel_would_be_told(
        self, conn, aconn
    ) -> None:
        seed_japanese(conn, 5)

        state = await _graph(aconn).ainvoke(
            _start(audience="a parent of young children"), _config()
        )

        preview = state["__interrupt__"][0].value
        assert preview["instruction"] == "You are a parent of young children."

    @pytest.mark.anyio
    async def test_the_approved_sentence_reaches_every_panelist(
        self, conn, aconn
    ) -> None:
        seed_japanese(conn, 5)
        llm = CountingLLM()
        graph = _graph(aconn, llm=llm)
        await graph.ainvoke(_start(audience="a parent of young children"), _config())

        await graph.ainvoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )

        assert llm.enacted == ["You are a parent of young children."] * 5

    @pytest.mark.anyio
    async def test_an_edited_sentence_is_what_runs(self, conn, aconn) -> None:
        """The edit *is* the human-in-the-loop. What is approved is what runs."""
        seed_japanese(conn, 5)
        llm = CountingLLM()
        graph = _graph(aconn, llm=llm)
        await graph.ainvoke(_start(audience="a parent of young children"), _config())

        await graph.ainvoke(
            Command(
                resume=GateDecision(
                    action="accept", instruction="You are a parent of two toddlers."
                ).model_dump()
            ),
            _config(),
        )

        assert llm.enacted == ["You are a parent of two toddlers."] * 5

    @pytest.mark.anyio
    async def test_the_backstop_still_guards_an_edit_the_classifier_passed(
        self, conn, aconn
    ) -> None:
        """The graph's own layer, and the last one before the prompt is built.

        The model classifier runs at the API boundary now, because whether a
        sentence may run is also the decision about whether it costs a run. This
        one is deterministic and costs nothing, so it runs here regardless — and
        it catches what a classifier reading meaning can miss.
        """
        seed_japanese(conn, 5)
        llm = CountingLLM()
        graph = _graph(aconn, llm=llm)
        await graph.ainvoke(_start(audience="a parent of young children"), _config())

        state = await graph.ainvoke(
            Command(
                resume=GateDecision(
                    action="accept",
                    instruction="You compare every headline you are shown.",
                ).model_dump()
            ),
            _config(),
        )

        assert llm.asked == 0
        assert state["__interrupt__"], "a refused edit returns to the gate"
        assert state["__interrupt__"][0].value["refusal_sentence"]

    @pytest.mark.anyio
    async def test_accepting_the_untouched_draft_costs_no_check(
        self, conn, aconn
    ) -> None:
        """Its verdict is cached from generation, so a reader out of checks can
        still run honestly by restoring the model's draft."""
        seed_japanese(conn, 5)
        generator = StubGenerator()
        graph = _graph(aconn, generator=generator)
        await graph.ainvoke(_start(audience="a parent of young children"), _config())

        await graph.ainvoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )

        assert generator.checked == []

    @pytest.mark.anyio
    async def test_a_refused_audience_never_reaches_the_gate(self, conn, aconn) -> None:
        """No panel is drawn and no reader is asked to approve something we have
        already decided not to run."""
        seed_japanese(conn, 5)
        graph = _graph(
            aconn, generator=StubGenerator({"a named celebrity": "real_person"})
        )

        with pytest.raises(RolePlayRefused) as refused:
            await graph.ainvoke(_start(audience="a named celebrity"), _config())

        assert refused.value.refusal == "real_person"

    @pytest.mark.anyio
    async def test_the_verdict_says_the_portrayal_was_instructed_not_sampled(
        self, conn, aconn
    ) -> None:
        """The honesty condition this feature is allowed to exist under. The
        demographics behind a verdict are surveyed; this part of the panel is a
        model acting a description, and a report that does not say so is claiming
        evidence it does not have."""
        seed_japanese(conn, 5)
        graph = _graph(aconn)
        await graph.ainvoke(_start(audience="a parent of young children"), _config())

        state = await graph.ainvoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )

        caveat = [n for n in state["result"].notices if "instructed" in n.message]
        assert caveat, state["result"].notices
        assert "You are a parent of young children." in caveat[0].message

    @pytest.mark.anyio
    async def test_a_demographics_only_verdict_carries_no_such_caveat(
        self, conn, aconn
    ) -> None:
        seed_japanese(conn, 5)
        graph = _graph(aconn)
        await graph.ainvoke(_start(), _config())

        state = await graph.ainvoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )

        assert not [n for n in state["result"].notices if "instructed" in n.message]


@pytest.mark.anyio
async def test_a_run_clocks_every_step_it_ran_and_a_rerun_adds_to_the_clock(
    conn, aconn, monkeypatch
) -> None:
    """033/#134: the run keeps its own time, per node, in the state — so the
    checkpointer carries the pre-gate steps across the human's wait, and the
    wait itself is never counted. A stub clock ticking once per read makes every
    node take exactly 1.0, so additivity is an equality, not a machine's speed.
    """
    seed_japanese(conn, 5)
    ticks = itertools.count()
    monkeypatch.setattr(graph_module, "_clock", lambda: float(next(ticks)))
    graph = _graph(aconn)

    first = await graph.ainvoke(_start(), _config())
    # `confirm` paused before it could write: a node that interrupts records
    # nothing, and the preview above the interrupt is cheap by rule.
    assert first["step_seconds"] == {"roleplay": 1.0, "select": 1.0}

    edited = first["__interrupt__"][0].value["query"]
    await graph.ainvoke(
        Command(resume=GateDecision(action="adjust", query=edited).model_dump()),
        _config(),
    )
    state = await graph.ainvoke(
        Command(resume=GateDecision(action="accept").model_dump()), _config()
    )

    # An adjust round ran `confirm` and `select` a second time each: the
    # re-run adds to the clock rather than replacing it.
    assert state["step_seconds"] == {
        "roleplay": 1.0,
        "select": 2.0,
        "confirm": 2.0,
        "vote": 1.0,
        "assemble": 1.0,
    }


def test_the_timer_keeps_a_sync_node_sync_and_an_async_node_async() -> None:
    """LangGraph decides thread-or-loop by `inspect.iscoroutinefunction`
    (langgraph/_internal/_runnable.py, `is_async_callable`). A sync node made
    async by its wrapper would run its blocking model call on the loop."""
    import inspect

    def blocking(state):
        return {}

    async def awaiting(state):
        return {}

    assert not inspect.iscoroutinefunction(graph_module._timed("b", blocking))
    assert inspect.iscoroutinefunction(graph_module._timed("a", awaiting))
