"""Pins for the streaming transport: the NDJSON event contract.

The agent's *behavior* (tool wiring, prompt, thread memory) is pinned in
test_analyst.py; here it's the wire — event order, both token dialects, and
the in-band error discipline.
"""

from collections.abc import Iterator

import psycopg
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.memory import InMemorySaver

from app.analyst import ToolDeps, stream_analyst
from app.vote import OutOfCredit, VoteResponse
from tests.factories import (
    ScriptedChatModel,
    StreamingScriptedChatModel,
    ndjson_events,
    seed_japanese,
    tool_call_message,
)
from tests.test_analyst import _deps, _result


def _lines(
    model: ScriptedChatModel,
    *,
    conn: psycopg.Connection,
    thread_id: str,
    deps: ToolDeps | None = None,
) -> list[str]:
    """One streamed turn with the shared fixture result and question — every
    test here varies only the model and what it asserts about the wire."""
    return list(
        stream_analyst(
            model=model,
            result=_result(),
            thread_id=thread_id,
            message="Why did it stop early?",
            checkpointer=InMemorySaver(),
            deps=deps or _deps(conn),
        )
    )


class TestStreamAnalyst:
    def test_a_turn_streams_tool_then_tokens_then_done(self, conn) -> None:
        """The whole contract in one transcript: the tool announces itself,
        the answer arrives in pieces, and the stream says it finished."""
        model = ScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="The interval cleared the band."),
            ]
        )

        events = ndjson_events(_lines(model, conn=conn, thread_id="s-1"))

        tool_at = events.index({"type": "tool", "name": "analyze_results"})
        first_token_at = next(i for i, e in enumerate(events) if e["type"] == "token")
        assert tool_at < first_token_at
        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert "".join(tokens) == "The interval cleared the band."
        assert events[-1] == {"type": "done"}
        # NDJSON discipline: every line parses alone, no blank tokens.
        assert all(e != {"type": "token", "text": ""} for e in events)

    def test_a_never_answering_model_streams_one_error_event(self, conn) -> None:
        """The step budget's stream face: the same fixed sentence a 502 used
        to carry, in-band and terminal — nothing follows it, least of all a
        `done` that would let the client mistake the turn for a clean finish."""
        # A one-message script repeats forever (see ScriptedChatModel).
        model = ScriptedChatModel(responses=[tool_call_message()])

        events = ndjson_events(_lines(model, conn=conn, thread_id="s-2"))

        errors = [e for e in events if e["type"] == "error"]
        # 8 = 2 * len(tools) + 2 with three tools — the pinned sentence tracks
        # the derived budget, so it moves when the tool list does.
        assert errors == [
            {
                "type": "error",
                "message": "analyst was still calling tools after 8 steps",
            }
        ]
        assert events[-1]["type"] == "error"
        assert {"type": "done"} not in events

    def test_error_events_never_carry_model_text(self, conn) -> None:
        """The discipline the whole error design exists for: the exception
        *type* reaches the wire, the exception *message* — where provider and
        model text live — never does."""

        class Leaky(StreamingScriptedChatModel):
            def _stream(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: object = None,
                **kwargs: object,
            ) -> Iterator[ChatGenerationChunk]:
                # The unreachable yield keeps this a generator, so the raise
                # erupts mid-iteration — where a real provider failure lands.
                raise RuntimeError("api key sk-secret")
                yield

        lines = _lines(Leaky(responses=[]), conn=conn, thread_id="s-3")
        events = ndjson_events(lines)

        assert events[-1] == {
            "type": "error",
            "message": "analyst failed: RuntimeError",
        }
        assert all("sk-secret" not in line for line in lines)

    def test_credit_exhaustion_mid_tool_speaks_its_own_sentence(self, conn) -> None:
        """OutOfCredit's message is codebase-authored and names its remedy
        (top up, re-run resumes free) — worth more on the wire than
        'analyst failed: OutOfCredit'. Terminal like every error event: the
        analyst's own next call would 402 anyway. The stub's message must
        still never leak — only the pipeline's fresh sentence travels."""

        class BrokeLLM:
            configuration = "broke"

            def vote(
                self, *, system_prompt: str, option_1: str, option_2: str
            ) -> VoteResponse:
                raise OutOfCredit("stub-provider-text")

        seed_japanese(conn, 2)
        model = ScriptedChatModel(
            responses=[
                tool_call_message(
                    name="run_panel_test",
                    args={"target_description": "Japanese homeowners"},
                )
            ]
        )

        lines = _lines(
            model,
            conn=conn,
            thread_id="s-5",
            deps=_deps(conn, panel_llm=BrokeLLM()),
        )
        events = ndjson_events(lines)

        assert events[-1]["type"] == "error"
        assert events[-1]["message"].startswith("OpenRouter credit is exhausted")
        assert {"type": "done"} not in events
        assert all("stub-provider-text" not in line for line in lines)

    def test_tokens_arrive_incrementally_not_as_one_block(self, conn) -> None:
        """The worked example above tolerates one whole-message token (the
        non-streaming dialect); this pins the delta dialect: many pieces,
        reassembling to the exact sentence."""
        model = StreamingScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="The interval cleared the band."),
            ]
        )

        events = ndjson_events(_lines(model, conn=conn, thread_id="s-4"))

        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert len(tokens) > 1
        assert "".join(tokens) == "The interval cleared the band."
        assert events[-1] == {"type": "done"}
