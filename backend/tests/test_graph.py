"""The evaluate run as a graph, with a human between selection and spending.

076/#166. What these tests defend is one property: **no panel is voted on whose
reading a human has not accepted** — and the corollary that the pause itself
costs nothing, because a gate that spends money before it asks is not a gate.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from app.graph import GateDecision, build_evaluate_graph
from app.schemas import TargetQuery
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


def _graph(conn, *, llm=None, screener=None, saver=None, generator=None):
    return build_evaluate_graph(
        conn=conn,
        llm=llm or CountingLLM(),
        screener=screener,
        generator=generator or StubGenerator(),
        checkpointer=saver or InMemorySaver(),
    )


def _japan_query() -> TargetQuery:
    """The settled reading the endpoint would seed for a JP-only run — the
    graph reads a done deal now, never a description (094)."""
    return TargetQuery(
        countries=["JP"],
        coverage="requested",
        min_age=18,
        max_age=100,
        gender=None,
        income_quintiles=[],
        education=[],
        traits=[],
        notices=[],
    )


def _start(**overrides) -> dict:
    return {
        "query": _japan_query(),
        "variants": _VARIANTS,
        "size": 5,
    } | overrides


def _config(thread: str = "t-1") -> dict:
    return {"configurable": {"thread_id": thread}}


def test_the_run_stops_before_it_buys_anything(conn) -> None:
    """The gate's whole claim. A pause that has already spent is not a gate —
    it is a receipt."""
    seed_japanese(conn, 5)
    llm = CountingLLM()

    state = _graph(conn, llm=llm).invoke(_start(), _config())

    assert state["__interrupt__"], "the run should be waiting for a human"
    assert llm.asked == 0


def test_the_pause_says_who_would_be_seated_and_what_it_would_cost(conn) -> None:
    """A reader can only accept what they can see: the reading, the count, who
    it seats, and the price of finding out."""
    seed_japanese(conn, 5)

    state = _graph(conn).invoke(_start(), _config())

    preview = state["__interrupt__"][0].value
    assert preview["matched"] == 5
    assert preview["query"]["countries"] == ["JP"]
    assert preview["composition"]["countries"] == {"JP": 5}
    assert preview["estimated_usd"] > 0


def test_accepting_buys_the_votes(conn) -> None:
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(conn, llm=llm)
    graph.invoke(_start(), _config())

    state = graph.invoke(
        Command(resume=GateDecision(action="accept").model_dump()), _config()
    )

    assert llm.asked == 5
    assert state["result"].counts.voted == 5


def test_adjusting_reseats_the_panel_without_paying_to_translate_again(conn) -> None:
    """Editing the reading is free and deterministic — pure SQL. A second
    translation would be paid, non-reproducible, and could quietly disagree
    with the edit it was meant to apply."""
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(conn, llm=llm)
    first = graph.invoke(_start(), _config())
    edited = first["__interrupt__"][0].value["query"]

    state = graph.invoke(
        Command(resume=GateDecision(action="adjust", query=edited).model_dump()),
        _config(),
    )

    # Re-seated and paused again, and no model of any kind was asked.
    assert state["__interrupt__"]
    assert llm.asked == 0


def test_an_adjustment_stops_again_rather_than_running_on(conn) -> None:
    """The edited reading is a new reading, and nobody has accepted it yet."""
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(conn, llm=llm)
    first = graph.invoke(_start(), _config())
    same = first["__interrupt__"][0].value["query"]

    state = graph.invoke(
        Command(resume=GateDecision(action="adjust", query=same).model_dump()),
        _config(),
    )

    assert state["__interrupt__"]
    assert llm.asked == 0


def test_an_audience_already_accepted_does_not_stop_again(conn) -> None:
    """The gate fires on the first run and whenever the audience changes — not
    on every run (077, amended). Iterating on headlines against a fixed
    audience would otherwise train the reader to dismiss an approval unread,
    which is weaker human-in-the-loop than one that fires when there is
    something to read."""
    seed_japanese(conn, 5)
    llm = CountingLLM()

    state = _graph(conn, llm=llm).invoke(
        _start(reading_accepted=True), _config("t-repeat")
    )

    assert "__interrupt__" not in state
    assert state["result"].counts.voted == 5


def test_a_target_the_pool_cannot_serve_is_refused_before_the_gate(conn) -> None:
    """Nothing to approve and nothing to spend: the refusal belongs where the
    panel is drawn, not after a human has been asked about an empty room."""
    seed_japanese(conn, 5)
    graph = _graph(conn)
    conn.execute("DELETE FROM personas")
    conn.commit()

    with pytest.raises(EmptyPanel):
        graph.invoke(_start(), _config())


def test_refused_text_never_reaches_the_panel(conn) -> None:
    """The screener's one remaining post: the vote. Nothing before the gate is
    text a model reads (094) — the controls are SQL and the audience has its
    own classifier — so a flagged headline is refused where headlines are first
    shown to a model, before any vote is bought."""
    seed_japanese(conn, 5)
    llm = CountingLLM()

    class Refusing:
        def screen(self, text: str) -> ScreeningVerdict:
            return ScreeningVerdict(flagged=True, reason="prompt injection")

    graph = _graph(conn, llm=llm, screener=Refusing())
    graph.invoke(_start(), _config())

    with pytest.raises(UnsafeInput):
        graph.invoke(
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


def test_a_preview_screens_nothing(conn) -> None:
    """No text a model reads exists before the gate any more: the controls are
    SQL, and the audience is guarded by the generator's classifier rather than
    the copy screener. A preview that paid for screening would be buying a
    check for a run that may never be accepted — and checking the wrong
    instrument's text at that."""
    seed_japanese(conn, 5)
    screener = CountingScreener()

    _graph(conn, screener=screener).invoke(_start(), _config())

    assert screener.seen == []


def test_the_headlines_are_screened_before_they_reach_the_panel(conn) -> None:
    """Deferred, never dropped: the vote is the step that shows a headline to a
    model, so the check has to land before it."""
    seed_japanese(conn, 5)
    screener = CountingScreener()
    graph = _graph(conn, screener=screener)
    graph.invoke(_start(), _config())

    graph.invoke(Command(resume=GateDecision(action="accept").model_dump()), _config())

    assert sorted(screener.seen) == sorted(_VARIANTS.values())


def test_the_same_filter_seats_the_same_people(conn) -> None:
    """PANEL_SEED is fixed, so an unchanged audience is an unchanged panel —
    which is exactly why the gate can skip a repeat run without hiding
    anything."""
    seed_japanese(conn, 20)
    graph = _graph(conn)

    first = graph.invoke(_start(), _config("t-a"))["__interrupt__"][0].value
    second = graph.invoke(_start(), _config("t-b"))["__interrupt__"][0].value

    assert PANEL_SEED == 0
    assert first["composition"] == second["composition"]


def test_an_edit_that_matches_nobody_costs_a_click_not_the_run(conn) -> None:
    """A human can edit the reading into an empty room, and must be able to
    edit their way back out of it.

    Raising here would be a trap rather than a refusal: the edit is already in
    state, so every later resume would re-run selection and fail the same way —
    the run unrecoverable, the money unspent but the work lost. The gate exists
    to invite exactly this experiment, so it has to survive it.
    """
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(conn, llm=llm)
    first = graph.invoke(_start(), _config("t-edit"))
    original = first["__interrupt__"][0].value["query"]
    nobody = original | {"min_age": 99, "max_age": 100}

    empty = graph.invoke(
        Command(resume=GateDecision(action="adjust", query=nobody).model_dump()),
        _config("t-edit"),
    )
    back = graph.invoke(
        Command(resume=GateDecision(action="adjust", query=original).model_dump()),
        _config("t-edit"),
    )
    done = graph.invoke(
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


def test_an_accept_with_nobody_seated_buys_nothing(conn) -> None:
    """The interface will not offer this, and the graph does not depend on the
    interface for it: a panel of zero has nobody to ask."""
    seed_japanese(conn, 5)
    llm = CountingLLM()
    graph = _graph(conn, llm=llm)
    first = graph.invoke(_start(), _config("t-zero"))
    nobody = first["__interrupt__"][0].value["query"] | {"min_age": 99, "max_age": 100}
    graph.invoke(
        Command(resume=GateDecision(action="adjust", query=nobody).model_dump()),
        _config("t-zero"),
    )

    state = graph.invoke(
        Command(resume=GateDecision(action="accept").model_dump()), _config("t-zero")
    )

    assert llm.asked == 0
    assert state["__interrupt__"][0].value["matched"] == 0


def test_a_paused_run_outlives_the_process_that_started_it(conn, pg_url) -> None:
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

    with PostgresSaver.from_conn_string(pg_url) as before:
        before.setup()
        paused = _graph(conn, llm=llm, saver=before).invoke(
            _start(), _config("t-restart")
        )

    with PostgresSaver.from_conn_string(pg_url) as after:
        resumed = _graph(conn, llm=llm, saver=after).invoke(
            Command(resume=GateDecision(action="accept").model_dump()),
            _config("t-restart"),
        )

    assert paused["__interrupt__"][0].value["matched"] == 5
    assert resumed["result"].counts.voted == 5


def test_what_a_restart_restores_is_the_panel_a_human_approved(conn, pg_url) -> None:
    """Not the filter — the people.

    Re-selecting on resume would be a second query, and a second query is a
    second answer: the pool can change under a paused run (a reseed, a new
    country). Whoever the reader accepted is who votes, or the approval was
    about somebody else.
    """
    seed_japanese(conn, 5)

    with PostgresSaver.from_conn_string(pg_url) as before:
        before.setup()
        graph = _graph(conn, saver=before)
        graph.invoke(_start(), _config("t-pool-change"))
        seated = [
            p.id for p in graph.get_state(_config("t-pool-change")).values["panel"]
        ]

    conn.execute("DELETE FROM personas")
    conn.commit()

    with PostgresSaver.from_conn_string(pg_url) as after:
        resumed = _graph(conn, saver=after).invoke(
            Command(resume=GateDecision(action="accept").model_dump()),
            _config("t-pool-change"),
        )

    assert len(seated) == 5
    assert resumed["result"].counts.voted == 5


def test_a_second_run_of_the_same_test_replays_for_nothing(conn) -> None:
    """The replay guarantee, exercised through the graph rather than asserted.

    Votes are cached on the fingerprint of the exact question asked, so running
    the same headlines past the same panel a second time buys no model calls at
    all. The $0 demo depends on this, which is why the vote loop was moved into
    a node unedited.
    """
    seed_japanese(conn, 5)
    first_llm, second_llm = CountingLLM(), CountingLLM()

    first = _graph(conn, llm=first_llm).invoke(
        _start(reading_accepted=True), _config("t-paid")
    )
    second = _graph(conn, llm=second_llm).invoke(
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

    def test_a_demographics_only_run_calls_no_generator(self, conn) -> None:
        """Blank means demographics only, and the common case must stay free."""
        seed_japanese(conn, 5)
        generator = StubGenerator()

        _graph(conn, generator=generator).invoke(_start(), _config())

        assert generator.drafted == []

    def test_the_gate_shows_the_sentence_the_panel_would_be_told(self, conn) -> None:
        seed_japanese(conn, 5)

        state = _graph(conn).invoke(
            _start(audience="a parent of young children"), _config()
        )

        preview = state["__interrupt__"][0].value
        assert preview["instruction"] == "You are a parent of young children."

    def test_the_approved_sentence_reaches_every_panelist(self, conn) -> None:
        seed_japanese(conn, 5)
        llm = CountingLLM()
        graph = _graph(conn, llm=llm)
        graph.invoke(_start(audience="a parent of young children"), _config())

        graph.invoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )

        assert llm.enacted == ["You are a parent of young children."] * 5

    def test_an_edited_sentence_is_what_runs(self, conn) -> None:
        """The edit *is* the human-in-the-loop. What is approved is what runs."""
        seed_japanese(conn, 5)
        llm = CountingLLM()
        graph = _graph(conn, llm=llm)
        graph.invoke(_start(audience="a parent of young children"), _config())

        graph.invoke(
            Command(
                resume=GateDecision(
                    action="accept", instruction="You are a parent of two toddlers."
                ).model_dump()
            ),
            _config(),
        )

        assert llm.enacted == ["You are a parent of two toddlers."] * 5

    def test_the_backstop_still_guards_an_edit_the_classifier_passed(
        self, conn
    ) -> None:
        """The graph's own layer, and the last one before the prompt is built.

        The model classifier runs at the API boundary now, because whether a
        sentence may run is also the decision about whether it costs a run. This
        one is deterministic and costs nothing, so it runs here regardless — and
        it catches what a classifier reading meaning can miss.
        """
        seed_japanese(conn, 5)
        llm = CountingLLM()
        graph = _graph(conn, llm=llm)
        graph.invoke(_start(audience="a parent of young children"), _config())

        state = graph.invoke(
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

    def test_accepting_the_untouched_draft_costs_no_check(self, conn) -> None:
        """Its verdict is cached from generation, so a reader out of checks can
        still run honestly by restoring the model's draft."""
        seed_japanese(conn, 5)
        generator = StubGenerator()
        graph = _graph(conn, generator=generator)
        graph.invoke(_start(audience="a parent of young children"), _config())

        graph.invoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )

        assert generator.checked == []

    def test_a_refused_audience_never_reaches_the_gate(self, conn) -> None:
        """No panel is drawn and no reader is asked to approve something we have
        already decided not to run."""
        seed_japanese(conn, 5)
        graph = _graph(
            conn, generator=StubGenerator({"a named celebrity": "real_person"})
        )

        with pytest.raises(RolePlayRefused) as refused:
            graph.invoke(_start(audience="a named celebrity"), _config())

        assert refused.value.refusal == "real_person"

    def test_the_verdict_says_the_portrayal_was_instructed_not_sampled(
        self, conn
    ) -> None:
        """The honesty condition this feature is allowed to exist under. The
        demographics behind a verdict are surveyed; this part of the panel is a
        model acting a description, and a report that does not say so is claiming
        evidence it does not have."""
        seed_japanese(conn, 5)
        graph = _graph(conn)
        graph.invoke(_start(audience="a parent of young children"), _config())

        state = graph.invoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )

        caveat = [n for n in state["result"].notices if "instructed" in n.message]
        assert caveat, state["result"].notices
        assert "You are a parent of young children." in caveat[0].message

    def test_a_demographics_only_verdict_carries_no_such_caveat(self, conn) -> None:
        seed_japanese(conn, 5)
        graph = _graph(conn)
        graph.invoke(_start(), _config())

        state = graph.invoke(
            Command(resume=GateDecision(action="accept").model_dump()), _config()
        )

        assert not [n for n in state["result"].notices if "instructed" in n.message]
