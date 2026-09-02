"""Pins for the streaming transport: the NDJSON event contract.

The agent's *behavior* (tool wiring, prompt, thread memory) is pinned in
test_analyst.py; here it's the wire — event order, both token dialects, and
the in-band error discipline.
"""

import logging
from collections.abc import Iterator

import psycopg
import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.memory import InMemorySaver

from app.analyst import ToolDeps, build_tools, stream_analyst
from tests.factories import (
    ScriptedChatModel,
    StreamingScriptedChatModel,
    ndjson_events,
    tool_call_message,
)
from tests.test_analyst import _deps, _result


async def _lines(
    model: ScriptedChatModel,
    *,
    conn: psycopg.AsyncConnection,
    thread_id: str,
    deps: ToolDeps | None = None,
) -> list[str]:
    """One streamed turn with the shared fixture result and question — every
    test here varies only the model and what it asserts about the wire."""
    return [
        line
        async for line in stream_analyst(
            model=model,
            result=_result(),
            thread_id=thread_id,
            message="Why did it stop early?",
            checkpointer=InMemorySaver(),
            deps=deps or _deps(conn),
        )
    ]


class TestStreamAnalyst:
    @pytest.mark.anyio
    async def test_a_turn_streams_tool_then_tokens_then_done(self, conn, aconn) -> None:
        """The whole contract in one transcript: the tool announces itself,
        the answer arrives in pieces, and the stream says it finished."""
        model = ScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="The interval cleared the band."),
            ]
        )

        events = ndjson_events(await _lines(model, conn=aconn, thread_id="s-1"))

        tool_at = events.index({"type": "tool", "name": "analyze_results"})
        first_token_at = next(i for i, e in enumerate(events) if e["type"] == "token")
        assert tool_at < first_token_at
        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert "".join(tokens) == "The interval cleared the band."
        assert events[-1] == {"type": "done"}
        # NDJSON discipline: every line parses alone, no blank tokens.
        assert all(e != {"type": "token", "text": ""} for e in events)

    @pytest.mark.anyio
    async def test_a_never_answering_model_streams_one_error_event(
        self, conn, aconn
    ) -> None:
        """The step budget's stream face: the same fixed sentence a 502 used
        to carry, in-band and terminal — nothing follows it, least of all a
        `done` that would let the client mistake the turn for a clean finish."""
        # A one-message script repeats forever (see ScriptedChatModel).
        model = ScriptedChatModel(responses=[tool_call_message()])

        events = ndjson_events(await _lines(model, conn=aconn, thread_id="s-2"))

        errors = [e for e in events if e["type"] == "error"]
        # Derived here the way it is derived there, rather than written down: the
        # budget is `2 * len(tools) + 2`, so it moves whenever the tool surface
        # does — which is the formula doing exactly what it is for, and a
        # hardcoded copy here would just turn that into a broken test. The
        # message is the assertion; the number is arithmetic both sides agree on.
        steps = 2 * len(build_tools(_result(), _deps(conn))) + 2
        assert errors == [
            {
                "type": "error",
                "message": f"analyst was still calling tools after {steps} steps",
            }
        ]
        assert events[-1]["type"] == "error"
        assert {"type": "done"} not in events

    @pytest.mark.anyio
    async def test_a_length_cut_streamed_turn_says_so(self, conn, aconn) -> None:
        """090/#195: a completion that hits ANALYST_MAX_COMPLETION_TOKENS
        arrives with finish_reason "length" — in the streamed dialect, inside
        the `message-finish` event's metadata. The cut text has already been
        delivered, so the turn must not end as if it were whole: the fixed
        sentence follows the tokens, terminal like every other error."""
        model = StreamingScriptedChatModel(
            responses=[
                AIMessage(
                    content="The interval cleared the",
                    response_metadata={"finish_reason": "length"},
                )
            ]
        )

        events = ndjson_events(await _lines(model, conn=aconn, thread_id="cut-1"))

        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert "".join(tokens) == "The interval cleared the"
        assert events[-1] == {
            "type": "error",
            "message": (
                "the answer hit the analyst's length ceiling and was cut off"
                " — ask a narrower question"
            ),
        }
        assert {"type": "done"} not in events

    @pytest.mark.anyio
    async def test_a_length_cut_whole_message_turn_says_so(self, conn, aconn) -> None:
        """The same cut in the other wire dialect (whole messages from a
        non-streaming model), where finish_reason rides the AIMessage's own
        response_metadata — 025's trap says the two branches must both be
        exercised or one of them is fiction."""
        model = ScriptedChatModel(
            responses=[
                AIMessage(
                    content="The interval cleared the",
                    response_metadata={"finish_reason": "length"},
                )
            ]
        )

        events = ndjson_events(await _lines(model, conn=aconn, thread_id="cut-2"))

        assert events[-1] == {
            "type": "error",
            "message": (
                "the answer hit the analyst's length ceiling and was cut off"
                " — ask a narrower question"
            ),
        }
        assert {"type": "done"} not in events

    @pytest.mark.anyio
    async def test_error_events_never_carry_model_text(self, conn, aconn) -> None:
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

        lines = await _lines(Leaky(responses=[]), conn=aconn, thread_id="s-3")
        events = ndjson_events(lines)

        assert events[-1] == {
            "type": "error",
            "message": "analyst failed: RuntimeError",
        }
        assert all("sk-secret" not in line for line in lines)

    @pytest.mark.anyio
    async def test_tokens_arrive_incrementally_not_as_one_block(
        self, conn, aconn
    ) -> None:
        """The worked example above tolerates one whole-message token (the
        non-streaming dialect); this pins the delta dialect: many pieces,
        reassembling to the exact sentence."""
        model = StreamingScriptedChatModel(
            responses=[
                tool_call_message(),
                AIMessage(content="The interval cleared the band."),
            ]
        )

        events = ndjson_events(await _lines(model, conn=aconn, thread_id="s-4"))

        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert len(tokens) > 1
        assert "".join(tokens) == "The interval cleared the band."
        assert events[-1] == {"type": "done"}


@pytest.mark.anyio
async def test_a_turn_logs_its_usage(conn, aconn, caplog) -> None:
    """070/#161: chat spend was unknowable because nothing captured it. Each
    model call in a turn carries usage_metadata; the turn logs one summed
    line, the way the vote loop logs "panel usage". Tokens only — langchain's
    streaming path drops the provider's cost field (review, verified), so a
    cost column here could only ever log invented zeros. Money is derived at
    measurement time from these tokens and a dated price."""
    model = ScriptedChatModel(
        responses=[
            tool_call_message(),
            AIMessage(
                content="The interval cleared the band.",
                usage_metadata={
                    "input_tokens": 900,
                    "output_tokens": 120,
                    "total_tokens": 1020,
                    "input_token_details": {"cache_read": 700},
                    "output_token_details": {"reasoning": 300},
                },
            ),
        ]
    )
    # The tool-call message carries usage too — a turn is every model call in
    # it, not just the one that produced the answer.
    model.responses[0].usage_metadata = {
        "input_tokens": 600,
        "output_tokens": 40,
        "total_tokens": 640,
    }

    with caplog.at_level(logging.INFO, logger="app.analyst"):
        await _lines(model, conn=aconn, thread_id="usage-1")

    (record,) = [r for r in caplog.records if "analyst usage" in r.message]
    message = record.getMessage()
    assert "thread_id=usage-1" in message
    assert "calls=2" in message
    assert "input_tokens=1500" in message
    assert "output_tokens=160" in message
    # Reported-coverage discipline, as in `total_usage`: absent is not zero,
    # so each optional sum travels with how many calls reported it.
    assert "cached_tokens=700/1" in message
    assert "reasoning_tokens=300/1" in message
    assert "cost" not in message


@pytest.mark.anyio
async def test_a_streamed_turn_logs_usage_from_the_finish_event(
    conn, aconn, caplog
) -> None:
    """The dialect production actually speaks (070/#161, probed live): a
    natively streaming model's usage arrives in the v3 `message-finish`
    event's `usage` key — the whole-message branch never fires there. The
    suite's non-streaming double kept this path invisible, which is 025's
    tool-routing trap wearing a new hat."""
    model = StreamingScriptedChatModel(
        responses=[
            AIMessage(
                content="The interval cleared the band.",
                usage_metadata={
                    "input_tokens": 800,
                    "output_tokens": 90,
                    "total_tokens": 890,
                    "output_token_details": {"reasoning": 250},
                },
            )
        ]
    )

    with caplog.at_level(logging.INFO, logger="app.analyst"):
        await _lines(model, conn=aconn, thread_id="usage-4")

    (record,) = [r for r in caplog.records if "analyst usage" in r.message]
    message = record.getMessage()
    assert "input_tokens=800" in message
    assert "reasoning_tokens=250/1" in message


@pytest.mark.anyio
async def test_a_turn_with_no_usage_logs_nothing(conn, aconn, caplog) -> None:
    """Doubles report no usage; a line full of zeros would be an invented
    measurement, the exact thing the ticket exists to kill."""
    model = ScriptedChatModel(
        responses=[AIMessage(content="The interval cleared the band.")]
    )

    with caplog.at_level(logging.INFO, logger="app.analyst"):
        await _lines(model, conn=aconn, thread_id="usage-2")

    assert not [r for r in caplog.records if "analyst usage" in r.message]


@pytest.mark.anyio
async def test_a_disconnected_turn_still_logs_its_spend(conn, aconn, caplog) -> None:
    """The likely early end of a turn is a closed tab, which arrives here as
    aclose(), not an exception — and money spent before the disconnect was
    still spent (review: four per-exit log calls missed exactly this path)."""
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="The interval cleared the band.",
                usage_metadata={
                    "input_tokens": 800,
                    "output_tokens": 90,
                    "total_tokens": 890,
                },
            )
        ]
    )
    deps = _deps(aconn)
    stream = stream_analyst(
        model=model,
        result=_result(),
        thread_id="usage-3",
        message="how close was it?",
        checkpointer=InMemorySaver(),
        deps=deps,
    )

    with caplog.at_level(logging.INFO, logger="app.analyst"):
        async for line in stream:
            if '"token"' in line:
                break
        await stream.aclose()

    (record,) = [r for r in caplog.records if "analyst usage" in r.message]
    assert "input_tokens=800" in record.getMessage()
