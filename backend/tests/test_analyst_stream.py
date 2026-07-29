"""Pins for the streaming transport (012b, user-built).

The first test is written out as the worked example; the TODO stubs below it
are yours. All of them are red until stream_analyst exists — that's the point.
"""

import json

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.analyst import stream_analyst
from tests.factories import ScriptedChatModel
from tests.test_analyst import _result, _tool_call_message


def _events(lines: list[str]) -> list[dict[str, str]]:
    return [json.loads(line) for line in lines]


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

        lines = list(
            stream_analyst(
                model=model,
                result=_result(),
                thread_id="s-1",
                message="Why did it stop early?",
                checkpointer=InMemorySaver(),
            )
        )
        events = _events(lines)

        assert {"type": "tool", "name": "analyze_results"} in events
        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert "".join(tokens) == "The interval cleared the band."
        assert events[-1] == {"type": "done"}
        # NDJSON discipline: every line parses alone, no blank tokens.
        assert all(e != {"type": "token", "text": ""} for e in events)

    # TODO(user): test_a_never_answering_model_streams_one_error_event —
    #   script a model that only calls tools; assert exactly one "error" event,
    #   that its message is the fixed overrun sentence, and that no "done"
    #   event follows it.

    # TODO(user): test_error_events_never_carry_model_text —
    #   script a model whose _generate raises RuntimeError("api key sk-secret");
    #   assert the error event names the exception type and "sk-secret" appears
    #   nowhere in any line. (The vote path's NoVotes test is the template.)

    # TODO(user): test_tokens_arrive_incrementally_not_as_one_block —
    #   this needs ScriptedChatModel to learn `_stream` (yield AIMessageChunk
    #   word by word); until then BaseChatModel falls back to _generate and the
    #   answer arrives as ONE token event, which the first test tolerates.
    #   Extending the fake is part of this unit — factories.py is yours here.
