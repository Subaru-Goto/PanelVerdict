"""Pins for the streaming transport: the NDJSON event contract.

The agent's *behavior* (tool wiring, prompt, thread memory) is pinned in
test_analyst.py; here it's the wire — event order, both token dialects, and
the in-band error discipline.
"""

from collections.abc import Iterator

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.memory import InMemorySaver

from app.analyst import stream_analyst
from tests.factories import (
    ScriptedChatModel,
    StreamingScriptedChatModel,
    ndjson_events,
)
from tests.test_analyst import _result, _tool_call_message


def _lines(model: ScriptedChatModel, *, thread_id: str) -> list[str]:
    """One streamed turn with the shared fixture result and question — every
    test here varies only the model and what it asserts about the wire."""
    return list(
        stream_analyst(
            model=model,
            result=_result(),
            thread_id=thread_id,
            message="Why did it stop early?",
            checkpointer=InMemorySaver(),
        )
    )


class TestStreamAnalyst:
    def test_a_turn_streams_tool_then_tokens_then_done(self) -> None:
        """The whole contract in one transcript: the tool announces itself,
        the answer arrives in pieces, and the stream says it finished."""
        model = ScriptedChatModel(
            responses=[
                _tool_call_message(),
                AIMessage(content="The interval cleared the band."),
            ]
        )

        events = ndjson_events(_lines(model, thread_id="s-1"))

        tool_at = events.index({"type": "tool", "name": "analyze_results"})
        first_token_at = next(i for i, e in enumerate(events) if e["type"] == "token")
        assert tool_at < first_token_at
        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert "".join(tokens) == "The interval cleared the band."
        assert events[-1] == {"type": "done"}
        # NDJSON discipline: every line parses alone, no blank tokens.
        assert all(e != {"type": "token", "text": ""} for e in events)

    def test_a_never_answering_model_streams_one_error_event(self) -> None:
        """The step budget's stream face: the same fixed sentence a 502 used
        to carry, in-band and terminal — nothing follows it, least of all a
        `done` that would let the client mistake the turn for a clean finish."""
        # A one-message script repeats forever (see ScriptedChatModel).
        model = ScriptedChatModel(responses=[_tool_call_message()])

        events = ndjson_events(_lines(model, thread_id="s-2"))

        errors = [e for e in events if e["type"] == "error"]
        assert errors == [
            {
                "type": "error",
                "message": "analyst was still calling tools after 4 steps",
            }
        ]
        assert events[-1]["type"] == "error"
        assert {"type": "done"} not in events

    def test_error_events_never_carry_model_text(self) -> None:
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

        lines = _lines(Leaky(responses=[]), thread_id="s-3")
        events = ndjson_events(lines)

        assert events[-1] == {
            "type": "error",
            "message": "analyst failed: RuntimeError",
        }
        assert all("sk-secret" not in line for line in lines)

    def test_tokens_arrive_incrementally_not_as_one_block(self) -> None:
        """The worked example above tolerates one whole-message token (the
        non-streaming dialect); this pins the delta dialect: many pieces,
        reassembling to the exact sentence."""
        model = StreamingScriptedChatModel(
            responses=[
                _tool_call_message(),
                AIMessage(content="The interval cleared the band."),
            ]
        )

        events = ndjson_events(_lines(model, thread_id="s-4"))

        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert len(tokens) > 1
        assert "".join(tokens) == "The interval cleared the band."
        assert events[-1] == {"type": "done"}
