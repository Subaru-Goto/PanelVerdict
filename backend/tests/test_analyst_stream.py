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

from app.analyst import CALLS_PER_TURN, ToolDeps, stream_analyst
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
    checkpointer: InMemorySaver | None = None,
) -> list[str]:
    """One streamed turn with the shared fixture result and question — every
    test here varies only the model and what it asserts about the wire. Pass
    a `checkpointer` to speak to the same thread twice; the default is a
    fresh saver, i.e. a first turn."""
    return [
        line
        async for line in stream_analyst(
            model=model,
            result=_result(),
            thread_id=thread_id,
            message="Why did it stop early?",
            checkpointer=checkpointer or InMemorySaver(),
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
    async def test_a_never_answering_model_ends_at_the_declared_budget(
        self, conn, aconn, caplog
    ) -> None:
        """052/#149's stream face, replacing the derived tripwire's: a model
        still calling tools when the declared per-turn call budget runs out
        has the turn ended for it, and the reader gets this codebase's fixed
        sentence as the reply — then `done`. Not an error: the turn ended,
        the thread survives, the next question starts fresh. The library's
        own injected English must never reach the wire — and the wall must
        announce itself to the operator, because on the wire alone a
        budget-ended turn is indistinguishable from a short answer."""
        # A one-message script repeats forever (see ScriptedChatModel).
        model = ScriptedChatModel(responses=[tool_call_message()])

        with caplog.at_level(logging.WARNING, logger="app.analyst"):
            lines = await _lines(model, conn=aconn, thread_id="s-2")
        events = ndjson_events(lines)

        (warning,) = [r for r in caplog.records if "model-call budget" in r.message]
        assert warning.levelno == logging.WARNING

        # The budget's currency is model calls, pinned by counting what each
        # one bought: every allowed call was a tool round.
        assert len([e for e in events if e["type"] == "tool"]) == CALLS_PER_TURN
        tokens = "".join(e["text"] for e in events if e["type"] == "token")
        assert tokens == (
            "This turn ran out of its model-call budget before finishing an "
            "answer. Ask again with a narrower question."
        )
        assert events[-1] == {"type": "done"}
        assert all(e["type"] != "error" for e in events)
        assert all("Model call limits exceeded" not in line for line in lines)

    @pytest.mark.anyio
    async def test_the_backstop_errors_when_the_budget_stops_counting(
        self, conn, aconn, monkeypatch
    ) -> None:
        """The stated relationship between the two limits, exercised: a
        full-budget turn executes a measured 21 supersteps and the backstop
        sits at 44 — a whole turn of margin — so it can only fire if the
        budget stops counting, simulated here by raising it out of the way.
        What must survive that day is an error event with fixed text,
        terminal, no `done`."""
        from app import analyst

        monkeypatch.setattr(analyst, "CALLS_PER_TURN", 99)
        model = ScriptedChatModel(responses=[tool_call_message()])

        events = ndjson_events(await _lines(model, conn=aconn, thread_id="b-1"))

        assert events[-1] == {
            "type": "error",
            "message": "analyst was still calling tools after 44 steps",
        }
        assert {"type": "done"} not in events

    @pytest.mark.anyio
    async def test_the_budget_is_per_turn_not_per_thread(self, conn, aconn) -> None:
        """The amendment's re-judgment, pinned: the conversation ceiling lives
        at the HTTP edge (045's daily turn caps, charged by 089), so a turn
        that burned its whole budget must not eat into the next one's. A
        thread whose first turn ended over budget answers the second turn
        normally."""
        model = ScriptedChatModel(
            responses=[tool_call_message()] * CALLS_PER_TURN
            + [AIMessage(content="Second turn answers.")]
        )
        # One saver, one thread, two turns — a fresh saver per call would
        # test nothing, since the count could only carry over through it.
        saver = InMemorySaver()

        first = ndjson_events(
            await _lines(model, conn=aconn, thread_id="b-2", checkpointer=saver)
        )
        second = ndjson_events(
            await _lines(model, conn=aconn, thread_id="b-2", checkpointer=saver)
        )

        assert first[-1] == {"type": "done"}
        first_tokens = "".join(e["text"] for e in first if e["type"] == "token")
        assert first_tokens.startswith("This turn ran out of its model-call budget")
        tokens = [e["text"] for e in second if e["type"] == "token"]
        assert "".join(tokens) == "Second turn answers."
        assert second[-1] == {"type": "done"}

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
    async def test_a_recovered_turn_is_not_reported_cut(self, conn, aconn) -> None:
        """The turn's LAST stated finish_reason decides: an early tool-call
        completion cut at the cap, which the model then recovered from with a
        whole answer, must end `done` — the cut sentence on a complete answer
        would be as dishonest as `done` on a fragment."""
        cut_tool_call = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "analyze_results",
                    "args": {},
                    "id": "c1",
                    "type": "tool_call",
                }
            ],
            response_metadata={"finish_reason": "length"},
        )
        model = ScriptedChatModel(
            responses=[
                cut_tool_call,
                AIMessage(
                    content="Recovered whole.",
                    response_metadata={"finish_reason": "stop"},
                ),
            ]
        )

        events = ndjson_events(await _lines(model, conn=aconn, thread_id="cut-3"))

        assert events[-1] == {"type": "done"}
        assert all(e["type"] != "error" for e in events)

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

    (record,) = [r for r in caplog.records if r.message == "analyst usage"]
    assert record.thread_id == "usage-1"
    assert record.calls == 2
    assert record.input_tokens == 1500
    assert record.output_tokens == 160
    # Reported-coverage discipline, as in `total_usage`: absent is not zero,
    # so each optional sum travels with how many calls reported it.
    assert (record.cached_tokens, record.cached_reported) == (700, 1)
    assert (record.reasoning_tokens, record.reasoning_reported) == (300, 1)
    assert not hasattr(record, "cost")


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

    (record,) = [r for r in caplog.records if r.message == "analyst usage"]
    # 047/#145: fields, not text — and the thread named on the line itself,
    # since it is written while the response is still streaming.
    assert record.thread_id == "usage-4"
    assert record.input_tokens == 800
    assert record.reasoning_tokens == 250
    assert record.reasoning_reported == 1


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

    (record,) = [r for r in caplog.records if r.message == "analyst usage"]
    assert record.input_tokens == 800
