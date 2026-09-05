import asyncio
import json
import threading

import psycopg
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from app.analyst import (
    _SYSTEM_PROMPT,
    ToolDeps,
    _BudgetEndsTheTurn,
    analysis_facts,
    build_tools,
    checkpointed_models,
    stream_analyst,
    vote_reasons,
)
from app.corpus import Embedder
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
            countries=(Locale.US,),
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
    def test_who_preferred_which_reaches_the_facts_recomputed_from_the_votes(
        self,
    ) -> None:
        """The split is not on the wire — it is derived here from the votes, so a
        client that doctored its tally cannot move it (041/#139)."""
        facts = analysis_facts(_result_with_voters())

        assert facts.splits is not None
        named = {split.dimension for split in facts.splits.dimensions}
        assert "age_band" in named and "conscientiousness" in named
        age = next(s for s in facts.splits.dimensions if s.dimension == "age_band")
        assert {row.level for row in age.rows} == {"20-29", "40-49", "80+"}

    def test_a_request_carrying_no_votes_claims_no_split(self) -> None:
        """Same reason `panel` is None there: a crosstab of nothing would be a
        claim about a panel that isn't present."""
        assert analysis_facts(_result()).splits is None

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

    def test_every_tool_reads_and_none_of_them_buys_a_panel(self, conn) -> None:
        names = {tool.name for tool in build_tools(_result(), _deps(conn))}

        assert names == {
            "analyze_results",
            "read_reasons",
            "explain_the_report",
        }
        assert "run_panel_test" not in names
        # 084/#175: top-n by cosine over five profiles said nothing about the
        # panel and could return an A-voter when asked who preferred B. "Who
        # preferred which" is analyze_results' split now (041/#139).
        assert "search_personas" not in names

    def test_analyze_results_hands_over_the_split_and_its_confounds(self, conn) -> None:
        """The JSON the model actually receives, not the model that built it —
        the only seam that proves the tool contract rather than the function."""
        (tool,) = [
            tool
            for tool in build_tools(_result_with_voters(), _deps(conn))
            if tool.name == "analyze_results"
        ]

        payload = json.loads(tool.invoke({}))

        splits = payload["splits"]
        assert splits["rope"] == [0.43, 0.57]
        traits = {
            split["dimension"]: split
            for split in splits["dimensions"]
            if split["demographic_confound"]
        }
        assert (
            "persona-seed-data" in traits["conscientiousness"]["demographic_confound"]
        )


def _deps(
    conn: psycopg.AsyncConnection, *, embedder: Embedder | None = None
) -> ToolDeps:
    """What the analyst's tools need at call time. Short, now that none of them
    can start a test: a connection and a canned embedder, since a real
    embedding is a paid call and no test here buys one."""
    return ToolDeps(conn=conn, embedder=embedder or FixedEmbedder(pointing(0)))


async def _run(
    model: ScriptedChatModel,
    *,
    conn: psycopg.AsyncConnection,
    checkpointer: BaseCheckpointSaver | None = None,
    thread_id: str = "t-1",
    message: str = "Why did it stop early?",
    result: EvaluateResponse | None = None,
    deps: ToolDeps | None = None,
) -> str:
    """One turn's answer, reassembled from the stream — these tests are about
    the agent's behavior, and the stream is the only transport it has.

    """
    events = ndjson_events(
        [
            line
            async for line in stream_analyst(
                model=model,
                result=result or _result(),
                owner="acct",
                thread_id=thread_id,
                message=message,
                checkpointer=checkpointer or InMemorySaver(),
                deps=deps or _deps(conn),
            )
        ]
    )
    return "".join(e["text"] for e in events if e["type"] == "token")


class TestAnalystAgent:
    @pytest.mark.anyio
    async def test_the_agent_runs_our_tool_and_returns_the_final_reply(
        self, conn, aconn
    ) -> None:
        """The one wiring fact worth pinning about create_agent: a ToolMessage
        carrying OUR recomputed facts only appears in the second prompt if the
        agent bound and executed the real analyze_results."""
        model = ScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="The interval cleared the band."),
            ]
        )

        reply = await _run(model, conn=aconn)

        assert reply == "The interval cleared the band."
        fed_back = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
        assert len(fed_back) == 1
        assert json.loads(str(fed_back[0].content))["polling"] == (
            "Polling stopped once the panel had already decided."
        )

    @pytest.mark.anyio
    async def test_one_tool_call_can_answer_why_the_panel_looks_wrong(
        self, conn, aconn
    ) -> None:
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

        reply = await _run(
            model,
            conn=aconn,
            result=_result_with_voters(),
            message="Why does a young Japanese panel include a 90-year-old?",
        )

        assert reply == "Ages ran 23 to 91."
        fed_back = [m for m in model.seen[1] if isinstance(m, ToolMessage)]
        panel = json.loads(str(fed_back[0].content))["panel"]
        assert (panel["age_min"], panel["age_max"]) == (23, 91)
        assert panel["countries"] == {"JP": 2, "US": 1}

    @pytest.mark.anyio
    async def test_a_question_needing_no_tool_is_answered_without_one(
        self, conn, aconn
    ) -> None:
        """ "What does a credible interval mean?" has no tool and needs none.
        The agent must not require a tool round to produce a turn — the
        prompt's licence to answer general questions directly is worthless if
        the loop cannot carry a tool-free answer."""
        model = ScriptedChatModel(
            responses=[AIMessage(content="It is the range the true share sits in.")]
        )

        events = ndjson_events(
            [
                line
                async for line in stream_analyst(
                    model=model,
                    result=_result(),
                    owner="acct",
                    thread_id="t-direct",
                    message="What does a credible interval mean?",
                    checkpointer=InMemorySaver(),
                    deps=_deps(aconn),
                )
            ]
        )

        assert [e for e in events if e["type"] == "tool"] == []
        assert "".join(e["text"] for e in events if e["type"] == "token") == (
            "It is the range the true share sits in."
        )
        assert events[-1] == {"type": "done"}

    @pytest.mark.anyio
    async def test_a_hallucinated_tool_name_does_not_crash_the_run(
        self, conn, aconn
    ) -> None:
        model = ScriptedChatModel(
            responses=[
                tool_call_message(name="drop_the_database"),
                AIMessage(content="Sorry, I cannot do that."),
            ]
        )

        reply = await _run(model, conn=aconn)

        assert reply == "Sorry, I cannot do that."
        # The framework replies to the bad call id itself; the pinned fact is
        # only that the run survives and the model gets *some* ToolMessage.
        assert any(isinstance(m, ToolMessage) for m in model.seen[1])

    @pytest.mark.anyio
    async def test_the_agent_owns_the_system_prompt_and_it_stays_constant(
        self, conn, aconn
    ) -> None:
        model = ScriptedChatModel(responses=[AIMessage(content="ok")])

        await _run(model, conn=aconn)

        first = model.seen[0][0]
        assert isinstance(first, SystemMessage)
        assert first.content == _SYSTEM_PROMPT
        # Zero interpolation, pinned: no request content can reach the seat
        # the instructions sit in.
        assert "{" not in _SYSTEM_PROMPT

    def test_the_prompt_affirms_an_ai_system_while_withholding_the_make(self) -> None:
        # Art. 50(1) requires the artificial nature affirmed; the machinery
        # rule withholds the model family. Pin the affirmation so a future
        # edit to the identity rule cannot silently drop the legal half —
        # prompt obedience is unassertable, but the sentence's presence is not.
        assert "an AI system" in _SYSTEM_PROMPT
        assert "never a person" in _SYSTEM_PROMPT

    def test_the_prompt_bounds_its_subject_and_fixes_the_shape_of_a_decline(
        self,
    ) -> None:
        # 091/#196: the general lane stays open (headlines in general), and
        # everything outside it is declined in a fixed shape — outside what it
        # covers, then what it can help with, and never a partial answer first.
        # Obedience is measured live by experiments/topic_boundary.py; the
        # sentence's presence is what the suite can pin.
        assert "how headlines work, what makes copy land" in _SYSTEM_PROMPT
        assert "outside what you cover" in _SYSTEM_PROMPT
        assert "what you can help with" in _SYSTEM_PROMPT
        assert "not even briefly" in _SYSTEM_PROMPT
        # Writing headlines is the product's neighbour, not its job: the
        # decline points at the real alternative, as the re-run refusal does.
        assert "you do not write them" in _SYSTEM_PROMPT

    @pytest.mark.anyio
    async def test_a_thread_remembers_its_tool_results_across_turns(
        self, conn, aconn
    ) -> None:
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

        await _run(
            model, conn=aconn, checkpointer=checkpointer, message="How sure are we?"
        )
        reply = await _run(model, conn=aconn, checkpointer=checkpointer, message="Why?")

        assert reply == "Because the interval cleared the band."
        third_prompt = model.seen[2]
        assert any(isinstance(m, ToolMessage) for m in third_prompt)
        assert any(
            isinstance(m, HumanMessage) and m.content == "How sure are we?"
            for m in third_prompt
        )

    def test_every_checkpointed_model_survives_the_serde_round_trip(self) -> None:
        """The Postgres saver stores state through JsonPlusSerializer, which
        rebuilds a pydantic model by re-importing its class — and answers a
        failure with a plain dict and a log line, not an error. Derived from
        the agent's real state schema, so a model added to the state is
        covered the day it appears, or this test names the field pool it
        needs extending with."""
        serde = JsonPlusSerializer()
        # The schema the checkpointer actually serializes is the middleware's
        # widened one (052/#149 added ModelCallLimitState's two counters), so
        # the walk starts from what `stream_analyst` wires, not from the base
        # AgentState it happens to extend.
        models = checkpointed_models(_BudgetEndsTheTurn.state_schema)
        assert models, "the walk found no models — the schema moved"

        # One valid instance per class, built from its own required fields; a
        # new required field fails here with its name, asking to be added.
        samples = {
            "content": "x",
            "role": "assistant",
            "tool_call_id": "t",
            "name": "f",
        }
        for model_cls in models:
            instance = model_cls(
                **{
                    name: samples[name]
                    for name, field in model_cls.model_fields.items()
                    if field.is_required()
                }
            )
            revived = serde.loads_typed(serde.dumps_typed(instance))
            assert type(revived) is model_cls

    @pytest.mark.anyio
    async def test_a_thread_survives_a_process_restart(
        self, conn, aconn, pg_url
    ) -> None:
        """The reason the saver moved to Postgres (#144): a second saver
        instance over the same database — a restarted process, or another
        worker — resumes the transcript the first one wrote, ToolMessages
        included, instead of silently answering from an empty thread."""
        model = ScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="98% for A."),
                AIMessage(content="Because the interval cleared the band."),
            ]
        )

        async with AsyncPostgresSaver.from_conn_string(pg_url) as saver:
            await saver.setup()
            await _run(
                model,
                conn=aconn,
                checkpointer=saver,
                thread_id="t-restart",
                message="How sure are we?",
            )
        # A fresh saver over the same database is what a restart leaves behind.
        async with AsyncPostgresSaver.from_conn_string(pg_url) as saver:
            reply = await _run(
                model,
                conn=aconn,
                checkpointer=saver,
                thread_id="t-restart",
                message="Why?",
            )

        assert reply == "Because the interval cleared the band."
        third_prompt = model.seen[2]
        assert any(isinstance(m, ToolMessage) for m in third_prompt)
        assert any(
            isinstance(m, HumanMessage) and m.content == "How sure are we?"
            for m in third_prompt
        )

    @pytest.mark.anyio
    async def test_threads_do_not_share_memory(self, conn, aconn) -> None:
        checkpointer = InMemorySaver()
        model = ScriptedChatModel(responses=[AIMessage(content="ok")])

        await _run(
            model,
            conn=aconn,
            checkpointer=checkpointer,
            thread_id="t-1",
            message="secret question",
        )
        await _run(
            model,
            conn=aconn,
            checkpointer=checkpointer,
            thread_id="t-2",
            message="hello",
        )

        second_thread_prompt = model.seen[1]
        assert not any(
            isinstance(m, HumanMessage) and "secret" in str(m.content)
            for m in second_thread_prompt
        )


class TestExplainingWhatTheReportMeans:
    """018/#124. The reader cannot see the code, so a concept question answered
    from the model's weights is a confident mismatch with what the system did,
    delivered to somebody with no way to check it."""

    @pytest.mark.anyio
    async def test_the_answer_comes_back_with_something_to_check(
        self, conn, aconn
    ) -> None:
        from app.corpus import seed_corpus
        from tests.test_corpus_retrieval import FakeEmbedder

        seed_corpus(conn, FakeEmbedder())
        (explain,) = [
            t
            for t in build_tools(_result(), _deps(aconn, embedder=FakeEmbedder()))
            if t.name == "explain_the_report"
        ]

        answer = json.loads(
            await explain.ainvoke({"question": "what is a practical tie"})
        )

        assert answer, "the corpus should have a passage on this"
        assert all(passage["citation"] for passage in answer)

    @pytest.mark.anyio
    async def test_a_question_the_corpus_cannot_answer_returns_nothing(
        self, conn, aconn
    ) -> None:
        """So the analyst says it does not know, rather than being handed the
        nearest passage and citing it."""
        from app.corpus import seed_corpus
        from tests.test_corpus_retrieval import FakeEmbedder

        seed_corpus(conn, FakeEmbedder())
        (explain,) = [
            t
            for t in build_tools(_result(), _deps(aconn, embedder=FakeEmbedder()))
            if t.name == "explain_the_report"
        ]

        assert (
            json.loads(await explain.ainvoke({"question": "how do I bake sourdough"}))
            == []
        )


class TestToolsGatheredOnOneConnection:
    """113/#243 finding 1: `ToolNode._afunc` ends with `asyncio.gather`, so a
    turn's tool calls run concurrently on the one request connection. The
    reproduced failure — `['tool A -> UndefinedColumn', 'tool B ->
    InFailedSqlTransaction']` — was B's perfectly fine statement dying because
    A had aborted the transaction they shared."""

    @pytest.mark.anyio
    async def test_a_tools_failure_cannot_fail_a_siblings_query(
        self, conn, aconn
    ) -> None:
        """On the autocommit connection /chat hands the tools (pinned by
        `test_no_transaction_outlives_a_chat_tools_read`), each read stands
        alone: there is no shared transaction for A's wreck to abort under B.
        B's embedding waits for A to have already failed, so this asserts the
        exact ordering the ticket reproduced rather than racing for it. A's
        failure is the ticket's own scenario — a wrong-dimension query vector,
        the shape a model swap produces."""
        from app.corpus import seed_corpus
        from tests.test_corpus_retrieval import FakeEmbedder

        persist_pool(conn, [make_persona(id_="US-00000")])
        seed_corpus(conn, FakeEmbedder())
        await aconn.set_autocommit(True)

        a_failed = threading.Event()

        class SplitEmbedder:
            """A vector no column can compare against for the search; a working
            one, held until the search has already failed, for the corpus."""

            def embed(self, texts: list[str]) -> list[list[float]]:
                if any("thrifty" in text for text in texts):
                    return [[1.0] for _ in texts]  # one dimension against 1536
                assert a_failed.wait(timeout=5), "tool A never failed"
                return FakeEmbedder().embed(texts)

        result = _result().model_copy(update={"votes": [make_panel_vote("US-00000")]})
        tools = {
            tool.name: tool
            for tool in build_tools(result, _deps(aconn, embedder=SplitEmbedder()))
        }

        async def doomed_search() -> str:
            # 084/#175 retired the tool this used to be; the wreck is the same
            # shape on the one embedding tool left, asked twice at once. The
            # question has to match a passage lexically: membership is decided
            # by the lexical gate and the vector only orders what passed it, so
            # an unmatched question came back [] unharmed (observed re-aiming
            # this test), and the wreck never happened.
            try:
                return await tools["explain_the_report"].ainvoke(
                    {"question": "is a practical tie thrifty"}
                )
            finally:
                a_failed.set()

        searched: object
        explained: object
        searched, explained = await asyncio.gather(
            doomed_search(),
            tools["explain_the_report"].ainvoke(
                {"question": "what is a practical tie"}
            ),
            return_exceptions=True,
        )

        # A's wreck is honestly A's own...
        assert isinstance(searched, Exception)
        assert "InFailedSqlTransaction" not in repr(searched)
        # ...and B, landing strictly after it, still gets its passages.
        assert not isinstance(explained, BaseException), explained
        passages = json.loads(str(explained))
        assert passages and all(passage["citation"] for passage in passages)


def test_a_concept_question_no_longer_routes_to_the_model_s_own_memory() -> None:
    """The prompt rule was the blocker this ticket names, and it was misrouting
    rather than being strict: it sent "what does a credible interval mean" to the
    weights, which is the one place the answer is not.

    The loophole it guarded still has to hold — a question about THIS run's panel
    goes to a tool, never to the corpus.
    """
    from app.analyst import _SYSTEM_PROMPT

    assert "do not reach for a tool at all" not in _SYSTEM_PROMPT
    assert "explain_the_report" in _SYSTEM_PROMPT


def test_the_analyst_is_asked_to_stay_under_the_code_s_very_short_text_line() -> None:
    """075/#165. The Code of Practice on Transparency of AI-generated Content
    exempts "very short text" — under 200 tokens — from machine-readable marking,
    and marking is not feasible for this product (the model provider ships no
    text watermark). Replies under that line are outside the obligation; the
    prompt asks for them. Best effort by construction: 025 routes doubles through
    the tools, so obedience is unassertable here — this pins that the ask is
    made and names the reason, so a prompt edit cannot drop it unnoticed.
    """
    from app.analyst import _SYSTEM_PROMPT

    assert "150 words" in _SYSTEM_PROMPT
    assert "200 tokens" in _SYSTEM_PROMPT
