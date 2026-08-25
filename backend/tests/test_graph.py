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
from app.pipeline import EmptyPanel
from app.screening import ScreeningVerdict, UnsafeInput
from app.targeting import PANEL_SEED
from tests.factories import StubTranslator, seed_japanese

_VARIANTS = {"a": "Save 50% today", "b": "Limited time: half price"}


class CountingLLM:
    """A panel model that records every vote it is asked to cast."""

    configuration = "counting"

    def __init__(self) -> None:
        self.asked = 0

    def vote(self, *, system_prompt: str, option_1: str, option_2: str):
        from tests.factories import voted

        self.asked += 1
        return voted("option_1", "clear discount framing")


class CountingTranslator(StubTranslator):
    """A translator that records how many paid translations were made."""

    def __init__(self, request) -> None:
        super().__init__(request)
        self.calls = 0

    def translate(self, *, description: str):
        self.calls += 1
        return super().translate(description=description)


def _graph(conn, *, llm=None, translator=None, screener=None, saver=None):
    from tests.factories import JAPAN_REQUEST

    return build_evaluate_graph(
        conn=conn,
        translator=translator or StubTranslator(JAPAN_REQUEST),
        llm=llm or CountingLLM(),
        screener=screener,
        checkpointer=saver or InMemorySaver(),
    )


def _start(description: str = "Japanese homeowners", **overrides) -> dict:
    return {
        "description": description,
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
    from tests.factories import JAPAN_REQUEST

    translator = CountingTranslator(JAPAN_REQUEST)
    graph = _graph(conn, translator=translator)
    first = graph.invoke(_start(), _config())
    edited = first["__interrupt__"][0].value["query"]

    graph.invoke(
        Command(resume=GateDecision(action="adjust", query=edited).model_dump()),
        _config(),
    )

    assert translator.calls == 1


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
    from tests.factories import JAPAN_REQUEST

    graph = _graph(conn, translator=StubTranslator(JAPAN_REQUEST))
    conn.execute("DELETE FROM personas")
    conn.commit()

    with pytest.raises(EmptyPanel):
        graph.invoke(_start(), _config())


def test_refused_text_never_reaches_selection(conn) -> None:
    """Screening comes first, as it does today — the last moment the customer's
    text has been copied only once."""
    seed_japanese(conn, 5)

    class Refusing:
        def screen(self, text: str) -> ScreeningVerdict:
            return ScreeningVerdict(flagged=True, reason="prompt injection")

    with pytest.raises(UnsafeInput):
        _graph(conn, screener=Refusing()).invoke(_start(), _config())


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
