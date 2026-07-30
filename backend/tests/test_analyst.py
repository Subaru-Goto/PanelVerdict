import json

import psycopg
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from langgraph.checkpoint.memory import InMemorySaver

from app.analyst import (
    _SYSTEM_PROMPT,
    ToolDeps,
    build_tools,
    analysis_facts,
    stream_analyst,
    vote_reasons,
)
from app.assembly import Embedder
from app.persistence import persist_pool
from app.schemas import (
    CoverageRung,
    EvaluateResponse,
    Locale,
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


def _result_with_voters() -> EvaluateResponse:
    """The live incident's own panel: a target asking for young Japanese
    people that seated a 91-year-old American."""
    return _result().model_copy(
        update={
            "votes": [
                make_panel_vote("a", age=23, country=Locale.JP, gender="female"),
                make_panel_vote("b", age=40, country=Locale.JP, gender="male"),
                make_panel_vote("c", age=91, country=Locale.US, gender="male"),
            ]
        }
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

    def test_a_run_that_polled_everyone_says_so_in_words(self) -> None:
        """`stop_reason: null` was the one fact in the payload with no sayable
        form — `_stopped_early_notice` composes nothing when a run doesn't stop
        early — so the analyst quoted the field name at the reader instead. The
        field is withheld rather than forbidden, since a model
        cannot quote a handle it was never given."""
        facts = analysis_facts(_result().model_copy(update={"stop_reason": None}))

        assert "stop_reason" not in facts.model_dump()
        assert facts.polling == "Polling ran through every matched panelist."

    def test_an_early_stop_gives_its_reason_in_the_report_s_own_words(self) -> None:
        """The clauses are `_stopped_early_notice`'s, so a reader who saw the
        report hears the same explanation from the analyst. The frame is
        weaker on purpose: a stop firing on the last chunk left nobody
        unpolled, and `EvaluateResponse` carries no `asked` to tell."""
        decisive = analysis_facts(_result()).polling
        tie = analysis_facts(
            _result().model_copy(update={"stop_reason": "practical_tie"})
        ).polling

        assert decisive == "Polling stopped once the panel had already decided."
        assert tie == (
            "Polling stopped once the difference was already credibly too small "
            "to matter."
        )

    def test_the_coverage_rung_ships_as_a_sentence_about_places(self) -> None:
        """Two bugs in one enum. `"requested"` is unsayable, so the analyst
        quoted it — and it reads like a verdict on the whole target when it
        only ever spoke about regions, which is the over-read the live reply
        made. A target that silently drops "young" still rates
        `requested`, so the wording says places and nothing else."""

        def region_match(rung: CoverageRung) -> str:
            result = _result()
            return analysis_facts(
                result.model_copy(
                    update={"query": result.query.model_copy(update={"coverage": rung})}
                )
            ).region_match

        assert "coverage" not in analysis_facts(_result()).model_dump()
        assert region_match("requested") == (
            "No place the target named had to be substituted."
        )
        assert region_match("approximated") == (
            "At least one place the target named was served by a stand-in "
            "region; a notice names which."
        )
        assert region_match("unmatched") == (
            "No place the target named could be matched: the panel spans the "
            "whole pool and carries no geographic targeting."
        )

    def test_it_summarizes_who_actually_voted(self) -> None:
        """The gap that cost a whole turn in live use: asked why a panel
        targeted at young people held a 90-year-old, no tool could say. These
        are that incident's own numbers — the spread is the answer."""
        panel = analysis_facts(_result_with_voters()).panel

        assert panel is not None
        assert (panel.age_min, panel.age_median, panel.age_max) == (23, 40, 91)
        # Biggest group first, so the model reads the panel's shape in order.
        assert list(panel.countries.items()) == [(Locale.JP, 2), (Locale.US, 1)]
        assert panel.genders == {"male": 2, "female": 1}

    def test_the_median_age_is_an_age_somebody_actually_is(self) -> None:
        """An even panel has no middle voter, and half a year of age would be
        a number no panelist could be asked about."""
        result = _result().model_copy(
            update={
                "votes": [make_panel_vote("a", age=30), make_panel_vote("b", age=41)]
            }
        )

        panel = analysis_facts(result).panel

        assert panel is not None
        assert panel.age_median in (30, 41)

    def test_a_result_carrying_no_votes_has_no_panel_summary(self) -> None:
        """Absent, not zeroed: an age range of 0–0 would be a claim about a
        panel, and there is no panel to claim anything about."""
        assert analysis_facts(_result()).panel is None

    def test_a_tally_without_both_variants_is_refused(self) -> None:
        broken = _result().model_copy(
            update={"tally": VoteTally(counts={"x": 50}, total=50)}
        )
        with pytest.raises(ValueError):
            analysis_facts(broken)


class TestVoteReasons:
    def test_reasons_are_grouped_by_the_headline_that_won_them(self) -> None:
        """The question is never "what did the panel say" — it is what the
        B-choosers said that the A-choosers did not. An ungrouped list makes
        the model do that join itself, from a field it has to trust."""
        result = _result().model_copy(
            update={
                "votes": [
                    make_panel_vote(
                        "p1", chosen="a", reason="The discount is concrete."
                    ),
                    make_panel_vote(
                        "p2", chosen="b", reason="Being a member feels earned."
                    ),
                    make_panel_vote(
                        "p3", chosen="a", reason="Fifty percent is unmissable."
                    ),
                ]
            }
        )

        reasons = vote_reasons(result)

        assert reasons["a"].headline == "Save 50% today"
        assert reasons["a"].reasons == [
            "The discount is concrete.",
            "Fifty percent is unmissable.",
        ]
        assert reasons["b"].headline == "Members save half"
        assert reasons["b"].reasons == ["Being a member feels earned."]

    def test_a_headline_nobody_chose_is_present_and_empty(self) -> None:
        """Empty, not absent: "nobody said anything for A" is a finding, and a
        missing key reads to the model as a tool that failed to report it."""
        result = _result().model_copy(
            update={"votes": [make_panel_vote("p1", chosen="b", reason="Warmer.")]}
        )

        reasons = vote_reasons(result)

        assert reasons["a"].reasons == []
        assert reasons["a"].headline == "Save 50% today"


class TestToolSurface:
    """What the analyst can reach, asserted rather than assumed.

    It used to hold `run_panel_test`, which bought a whole new panel — the only
    path by which a model in this system could spend money, reachable in
    principle by a crafted headline becoming a vote reason that `read_reasons`
    hands back. Gating it behind a request field would have closed that path;
    removing it deletes the path, and leaves no flag for a later change to get
    wrong. Re-running belongs to the report's Test again, which goes through
    /evaluate where the screening and the caps already live.
    """

    def test_every_tool_reads_and_none_of_them_spends(self, conn) -> None:
        names = {tool.name for tool in build_tools(_result(), _deps(conn))}

        assert names == {"analyze_results", "search_personas", "read_reasons"}
        assert "run_panel_test" not in names


def _deps(conn: psycopg.Connection, *, embedder: Embedder | None = None) -> ToolDeps:
    """What the analyst's tools need at call time. Short, now that none of them
    can start a test: a connection and a canned embedder, since a real
    embedding is a paid call and no test here buys one."""
    return ToolDeps(conn=conn, embedder=embedder or FixedEmbedder(pointing(0)))


def _run(
    model: ScriptedChatModel,
    *,
    conn: psycopg.Connection,
    checkpointer: InMemorySaver | None = None,
    thread_id: str = "t-1",
    message: str = "Why did it stop early?",
    result: EvaluateResponse | None = None,
    deps: ToolDeps | None = None,
) -> str:
    """One turn's answer, reassembled from the stream — these tests are about
    the agent's behavior, and the stream is the only transport it has.

    """
    events = ndjson_events(
        stream_analyst(
            model=model,
            result=result or _result(),
            thread_id=thread_id,
            message=message,
            checkpointer=checkpointer or InMemorySaver(),
            deps=deps or _deps(conn),
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
        assert json.loads(str(fed_back[0].content))["polling"] == (
            "Polling stopped once the panel had already decided."
        )

    def test_one_tool_call_can_answer_why_the_panel_looks_wrong(self, conn) -> None:
        """This ticket's whole pin, end to end: the live incident asked why a
        young-Japanese target seated a 90-year-old and the analyst looped
        until the budget killed the turn. One analyze_results call now
        carries the spread that answers it."""
        model = ScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="Ages ran 23 to 91."),
            ]
        )

        reply = _run(
            model,
            conn=conn,
            result=_result_with_voters(),
            message="Why does a young Japanese panel include a 90-year-old?",
        )

        assert reply == "Ages ran 23 to 91."
        fed_back = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
        panel = json.loads(str(fed_back[0].content))["panel"]
        assert (panel["age_min"], panel["age_max"]) == (23, 91)
        assert panel["countries"] == {"JP": 2, "US": 1}

    def test_the_agent_searches_only_this_tests_panel(self, conn) -> None:
        """search_personas end to end: the query text is embedded, the panel
        scope comes from result.votes, and the ToolMessage lists panelists
        nearest first. The outsider matches the query PERFECTLY and still may
        not appear — scope beats similarity."""
        persist_pool(
            conn,
            [
                # Distinct ages so the rendered summaries differ — the panel
                # is described by who these people are, never by their ids.
                make_assembled(
                    make_persona(id_="US-00000", age=61), embedding=pointing(1)
                ),
                make_assembled(
                    make_persona(id_="US-00001", age=27), embedding=pointing(0)
                ),
                make_assembled(
                    make_persona(id_="US-00002", age=44), embedding=pointing(0)
                ),
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
            deps=_deps(conn, embedder=FixedEmbedder(pointing(0))),
        )

        assert reply == "Two panelists match."
        fed_back = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
        found = json.loads(str(fed_back[0].content))
        # Length is half the assertion: the off-panel persona is a perfect
        # query match, so it would arrive as a third result if scope failed.
        assert len(found) == 2
        assert found[0].startswith("A 27-year-old")
        assert found[1].startswith("A 61-year-old")

    def test_a_search_never_hands_the_model_a_persona_id(self, conn) -> None:
        """The lesson the analyst was breaking in live use: an id
        identifies a row, not a reader. Enforced by absence — the model
        cannot quote a handle it was never given."""
        persist_pool(
            conn, [make_assembled(make_persona(id_="US-00000"), embedding=pointing(0))]
        )
        model = ScriptedChatModel(
            responses=[
                tool_call_message(name="search_personas", args={"query": "thrifty"}),
                AIMessage(content="One panelist matches."),
            ]
        )
        result = _result().model_copy(update={"votes": [make_panel_vote("US-00000")]})

        _run(model, conn=conn, result=result)

        fed_back = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
        assert "US-00000" not in str(fed_back[0].content)

    def test_a_question_needing_no_tool_is_answered_without_one(self, conn) -> None:
        """ "What does a credible interval mean?" has no tool and needs none.
        The agent must not require a tool round to produce a turn — the
        prompt's licence to answer general questions directly is worthless if
        the loop cannot carry a tool-free answer."""
        model = ScriptedChatModel(
            responses=[AIMessage(content="It is the range the true share sits in.")]
        )

        events = ndjson_events(
            stream_analyst(
                model=model,
                result=_result(),
                thread_id="t-direct",
                message="What does a credible interval mean?",
                checkpointer=InMemorySaver(),
                deps=_deps(conn),
            )
        )

        assert [e for e in events if e["type"] == "tool"] == []
        assert "".join(e["text"] for e in events if e["type"] == "token") == (
            "It is the range the true share sits in."
        )
        assert events[-1] == {"type": "done"}

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
