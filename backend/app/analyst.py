"""The 'Ask the analyst' agent: LangChain's `create_agent` over our tools.

The LLM decides *when* to call a tool; deterministic code decides *how* — every
number the analyst can cite comes out of `verdict.py`, recomputed from the
tally. Conversation memory is a server-side checkpointer keyed by `thread_id`:
the checkpointed transcript keeps ToolMessages, so a follow-up is answered from
context instead of re-buying tool calls a text-only replay would drop.
In-memory in v1 — a restart forgets threads and a second worker would not
share them, both acceptable at demo scale; the Postgres checkpointer is the
scale-up path, not a redesign.
"""

from collections.abc import Iterator

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError
from openai import APIStatusError
from pydantic import BaseModel

from app.schemas import (
    ChatStreamEvent,
    CoverageRung,
    DoneEvent,
    ErrorEvent,
    EvaluateResponse,
    PanelCounts,
    PanelVerdict,
    StopReason,
    TokenEvent,
    ToolEvent,
)
from app.verdict import panel_verdict


def _failure_sentence(error: Exception) -> str:
    """The exception *type* is the only part of a failure safe to forward:
    messages can carry provider responses and the model's own output."""
    return f"analyst failed: {type(error).__name__}"


# A constant with zero interpolation, so no request content — not the user's
# words, not the test payload — can reach the instructions that constrain the
# analyst. Everything variable arrives as a ToolMessage the model asked for.
_SYSTEM_PROMPT = (
    "You are the analyst for one synthetic-panel A/B test: a panel of sampled, "
    "synthetic personas — not real people — was shown two headline variants and "
    "each cast a forced vote between them.\n"
    "Rules:\n"
    "- Call a tool before citing any number; answer only from tool results, and "
    "say so when they cannot answer the question.\n"
    "- The headline number is a preference share of the panel, never a "
    "click-through rate: real readers mostly see one variant, and the panel is "
    "unvalidated where two variants say the same thing differently.\n"
    "- Plain language: prefer 'tie zone' over ROPE and spell out what an "
    "interval means; keep replies to a few sentences."
)


class AnalysisFacts(BaseModel):
    """What `analyze_results` hands the model, spelled out rather than a loose
    dict — the shape is the tool's contract with the prompt."""

    variants: dict[str, str]
    tally: dict[str, int]
    counts: PanelCounts
    stop_reason: StopReason | None
    coverage: CoverageRung
    notices: list[str]
    verdict: PanelVerdict


def analysis_facts(result: EvaluateResponse) -> AnalysisFacts:
    """Every number of the current test, recomputed from the tally.

    Recomputed rather than read off the request's verdict, so every figure the
    analyst cites was derived by our own math from one input — a client that
    doctored the verdict fields cannot make the analyst repeat them.
    """
    counts = result.tally.counts
    if set(counts) != {"a", "b"}:
        raise ValueError(f"tally names variants {sorted(counts)}, expected a and b")
    return AnalysisFacts(
        variants=result.variants,
        tally=counts,
        counts=result.counts,
        stop_reason=result.stop_reason,
        coverage=result.query.coverage,
        # Backend-composed sentences (never provider text), so safe to forward.
        notices=[notice.message for notice in result.notices],
        verdict=panel_verdict(preferring_b=counts["b"], total=result.tally.total),
    )


def build_tools(result: EvaluateResponse) -> list[BaseTool]:
    """The tools for one request, closed over that request's test."""

    @tool
    def analyze_results() -> str:
        """All the numbers of this test: the verdict recomputed from the vote
        tally, plus counts, stop reason, coverage and notices. Call this before
        citing any figure."""
        return analysis_facts(result).model_dump_json()

    return [analyze_results]


def stream_analyst(
    *,
    model: BaseChatModel,
    result: EvaluateResponse,
    thread_id: str,
    message: str,
    checkpointer: BaseCheckpointSaver,
) -> Iterator[str]:
    """Yield the agent's turn as NDJSON lines — one `ChatStreamEvent` each.

    The agent is rebuilt per request because the tools close over the request's
    test; the *thread* survives in the shared checkpointer, so the rebuilt
    agent resumes the same transcript — including its earlier ToolMessages.
    A stream cannot change its HTTP status after the first byte, so every
    failure becomes one in-band `error` event carrying the fixed sentence a
    status code would otherwise have carried. Nothing the model or provider
    wrote may ever appear in an error event.
    """
    tools = build_tools(result)

    # The step budget, per turn, derived not tuned: one model-then-tools round
    # per available tool (two supersteps each, in langgraph's currency) plus
    # the closing model step, plus one — the limit must strictly exceed the
    # steps executed, measured: a one-tool round errors at 3 and passes at 4.
    # A model still calling tools past the budget is looping, and the budget
    # converts runaway spend into a visible failure.
    limit = 2 * len(tools) + 2

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )

    def line(event: ChatStreamEvent) -> str:
        return event.model_dump_json() + "\n"

    try:
        stream = agent.stream_events(
            {"messages": [HumanMessage(content=message)]},
            {"configurable": {"thread_id": thread_id}, "recursion_limit": limit},
            version="v3",
        )
        for event in stream:
            data = event["params"]["data"]
            if event["method"] == "tools" and data.get("event") == "tool-started":
                yield line(ToolEvent(name=data["tool_name"]))
            elif event["method"] == "messages":
                payload = data[0] if isinstance(data, tuple) else data

                if isinstance(payload, AIMessage):
                    if payload.text:
                        yield line(TokenEvent(text=payload.text))
                elif (
                    isinstance(payload, dict)
                    and payload.get("event") == "content-block-delta"
                ):
                    delta = payload.get("delta", {})
                    if delta.get("type") == "text-delta" and delta.get("text"):
                        yield line(TokenEvent(text=delta["text"]))
    except GraphRecursionError:
        yield line(
            ErrorEvent(message=f"analyst was still calling tools after {limit} steps")
        )
        return
    except APIStatusError as error:
        yield line(
            ErrorEvent(
                message="OpenRouter credit exhausted (402)"
                if error.status_code == 402
                else _failure_sentence(error)
            )
        )
        return
    except Exception as error:
        # Broad on purpose — the stream is the only channel left.
        yield line(ErrorEvent(message=_failure_sentence(error)))
        return
    yield line(DoneEvent())
