import json

import psycopg
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from langgraph.checkpoint.memory import InMemorySaver

from app.analyst import _SYSTEM_PROMPT, analysis_facts, stream_analyst
from app.assembly import Embedder
from app.persistence import persist_pool
from app.schemas import (
    EvaluateResponse,
    PanelCounts,
    PanelVerdict,
    PreferenceExposure,
    PreferenceProbability,
    TargetQuery,
    VoteTally,
)
from app.verdict import panel_verdict
from tests.factories import (
    FixedEmbedder,
    ScriptedChatModel,
    make_assembled,
    make_panel_vote,
    make_persona,
    ndjson_events,
    pointing,
    tool_call_message,
)


def _result(*, preferring_b: int = 14, total: int = 50) -> EvaluateResponse:
    """A response whose verdict field is deliberately absurd, so any test that
    finds real numbers in the facts proves they were recomputed, not trusted."""
    bogus = PanelVerdict(
        share_preferring_b=0.99,
        probability_majority_prefers_b=0.99,
        credible_interval=(0.98, 1.0),
        credible_mass=0.95,
        rope=(0.43, 0.57),
        probability_meaningfully_preferred=PreferenceProbability(a=0.0, b=0.99),
        probability_practical_tie=0.01,
        detectable_gap=None,
        expected_preference_shortfall=PreferenceExposure(
            shipping_a=0.5, shipping_b=0.0
        ),
    )
    return EvaluateResponse(
        verdict=bogus,
        tally=VoteTally(
            counts={"a": total - preferring_b, "b": preferring_b}, total=total
        ),
        counts=PanelCounts(requested=200, matched=200, voted=total),
        query=TargetQuery(
            countries=("US",),
            coverage="requested",
            min_age=18,
            max_age=100,
            gender=None,
            income_quintiles=(),
            education=(),
            traits=(),
            notices=(),
        ),
        notices=(),
        stop_reason="decisive",
        variants={"a": "Save 50% today", "b": "Members save half"},
        votes=[],
    )


class TestAnalysisFacts:
    def test_the_verdict_is_recomputed_from_the_tally_not_trusted(self) -> None:
        facts = analysis_facts(_result())
        reference = panel_verdict(preferring_b=14, total=50)

        assert facts.verdict.share_preferring_b == reference.share_preferring_b
        assert facts.verdict.credible_interval == reference.credible_interval

    def test_it_carries_the_run_facts_beside_the_math(self) -> None:
        facts = analysis_facts(_result())

        assert facts.variants == {"a": "Save 50% today", "b": "Members save half"}
        assert facts.counts == PanelCounts(requested=200, matched=200, voted=50)
        assert facts.stop_reason == "decisive"
        assert facts.coverage == "requested"

    def test_a_tally_without_both_variants_is_refused(self) -> None:
        broken = _result().model_copy(
            update={"tally": VoteTally(counts={"x": 50}, total=50)}
        )
        with pytest.raises(ValueError):
            analysis_facts(broken)


def _run(
    model: ScriptedChatModel,
    *,
    conn: psycopg.Connection,
    checkpointer: InMemorySaver | None = None,
    thread_id: str = "t-1",
    message: str = "Why did it stop early?",
    result: EvaluateResponse | None = None,
    embedder: Embedder | None = None,
) -> str:
    """One turn's answer, reassembled from the stream — these tests are about
    the agent's behavior, and the stream is the only transport it has."""
    events = ndjson_events(
        stream_analyst(
            model=model,
            result=result or _result(),
            thread_id=thread_id,
            message=message,
            checkpointer=checkpointer or InMemorySaver(),
            conn=conn,
            embedder=embedder or FixedEmbedder(pointing(0)),
        )
    )
    return "".join(e["text"] for e in events if e["type"] == "token")


class TestAnalystAgent:
    def test_the_agent_runs_our_tool_and_returns_the_final_reply(self, conn) -> None:
        """The one wiring fact worth pinning about create_agent: a ToolMessage
        carrying OUR recomputed facts only appears in the second prompt if the
        agent bound and executed the real analyze_results."""
        model = ScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="The interval cleared the band."),
            ]
        )

        reply = _run(model, conn=conn)

        assert reply == "The interval cleared the band."
        fed_back = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
        assert len(fed_back) == 1
        assert json.loads(str(fed_back[0].content))["stop_reason"] == "decisive"

    def test_the_agent_searches_only_this_tests_panel(self, conn) -> None:
        """search_personas end to end: the query text is embedded, the panel
        scope comes from result.votes, and the ToolMessage lists panelists
        nearest first. The outsider matches the query PERFECTLY and still may
        not appear — scope beats similarity (012 decision log)."""
        persist_pool(
            conn,
            [
                make_assembled(make_persona(id_="US-00000"), embedding=pointing(1)),
                make_assembled(make_persona(id_="US-00001"), embedding=pointing(0)),
                make_assembled(make_persona(id_="US-00002"), embedding=pointing(0)),
            ],
        )
        model = ScriptedChatModel(
            responses=[
                tool_call_message(name="search_personas", args={"query": "thrifty"}),
                AIMessage(content="Two panelists match."),
            ]
        )
        result = _result().model_copy(
            update={"votes": [make_panel_vote("US-00000"), make_panel_vote("US-00001")]}
        )

        reply = _run(
            model,
            conn=conn,
            result=result,
            embedder=FixedEmbedder(pointing(0)),
        )

        assert reply == "Two panelists match."
        fed_back = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
        found = json.loads(str(fed_back[0].content))
        assert [p["id"] for p in found] == ["US-00001", "US-00000"]

    def test_a_hallucinated_tool_name_does_not_crash_the_run(self, conn) -> None:
        model = ScriptedChatModel(
            responses=[
                tool_call_message(name="drop_the_database"),
                AIMessage(content="Sorry, I cannot do that."),
            ]
        )

        reply = _run(model, conn=conn)

        assert reply == "Sorry, I cannot do that."
        # The framework replies to the bad call id itself; the pinned fact is
        # only that the run survives and the model gets *some* ToolMessage.
        assert any(isinstance(m, ToolMessage) for m in model.seen[1])

    def test_the_agent_owns_the_system_prompt_and_it_stays_constant(self, conn) -> None:
        model = ScriptedChatModel(responses=[AIMessage(content="ok")])

        _run(model, conn=conn)

        first = model.seen[0][0]
        assert isinstance(first, SystemMessage)
        assert first.content == _SYSTEM_PROMPT
        # Zero interpolation, pinned: no request content can reach the seat
        # the instructions sit in.
        assert "{" not in _SYSTEM_PROMPT

    def test_a_thread_remembers_its_tool_results_across_turns(self, conn) -> None:
        """The reason the checkpointer exists: turn two's prompt still carries
        turn one's ToolMessage, so a follow-up needs no repeat tool call."""
        checkpointer = InMemorySaver()
        model = ScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="98% for A."),
                AIMessage(content="Because the interval cleared the band."),
            ]
        )

        _run(model, conn=conn, checkpointer=checkpointer, message="How sure are we?")
        reply = _run(model, conn=conn, checkpointer=checkpointer, message="Why?")

        assert reply == "Because the interval cleared the band."
        third_prompt = model.seen[2]
        assert any(isinstance(m, ToolMessage) for m in third_prompt)
        assert any(
            isinstance(m, HumanMessage) and m.content == "How sure are we?"
            for m in third_prompt
        )

    def test_threads_do_not_share_memory(self, conn) -> None:
        checkpointer = InMemorySaver()
        model = ScriptedChatModel(responses=[AIMessage(content="ok")])

        _run(
            model,
            conn=conn,
            checkpointer=checkpointer,
            thread_id="t-1",
            message="secret question",
        )
        _run(
            model,
            conn=conn,
            checkpointer=checkpointer,
            thread_id="t-2",
            message="hello",
        )

        second_thread_prompt = model.seen[1]
        assert not any(
            isinstance(m, HumanMessage) and "secret" in str(m.content)
            for m in second_thread_prompt
        )
