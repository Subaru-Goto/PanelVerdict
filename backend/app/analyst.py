"""The 'Ask the analyst' agent: LangChain's `create_agent` over our tools (012).

The LLM decides *when* to call a tool; deterministic code decides *how* — every
number the analyst can cite comes out of `verdict.py`, recomputed from the
tally. Conversation memory is a server-side checkpointer keyed by `thread_id`
(user decision, on the ticket): the checkpointed transcript keeps ToolMessages,
so a follow-up is answered from context instead of re-buying tool calls a
text-only replay would drop. In-memory in v1 — a restart forgets threads and a
second worker would not share them, both acceptable at demo scale; the Postgres
checkpointer is the scale-up path, not a redesign.

`create_agent` replaced a hand-rolled loop on 2026-07-29 (user decision, on the
ticket): graph *authoring* stays v2, the modern API does not.
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
    CoverageRung,
    EvaluateResponse,
    PanelCounts,
    PanelVerdict,
    StopReason,
)
from app.verdict import panel_verdict
from app.vote import OutOfCredit


class AnalystLoopOverrun(Exception):
    """The agent was still calling tools when the step budget ran out.

    Every step is a paid call, so a run that never answers converts into a
    visible failure instead of an invisible bill. Fixed text only — nothing the
    model produced travels in the message.
    """


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

    Same agent, same step budget, same failure *meanings* as `run_analyst` —
    but a stream cannot change its HTTP status after the first byte, so every
    failure becomes one in-band `error` event carrying the same fixed sentence
    a status code used to carry. Nothing the model or provider wrote may ever
    appear in an error event.
    """
    # TODO(user) 1: build the tools and the agent exactly as run_analyst does,
    #   and derive the same step budget.
    #
    # TODO(user) 2: iterate the modern streaming API —
    #       agent.stream(
    #           {"messages": [HumanMessage(content=message)]},
    #           {"configurable": {"thread_id": thread_id},
    #            "recursion_limit": limit},
    #           stream_mode="messages",
    #       )
    #   Each item is a (message_chunk, metadata) pair. Decide per pair:
    #     - a ToolMessage means a tool just finished → yield a "tool" event
    #       with its name (the dock's "checking the numbers…" moment);
    #     - an AIMessageChunk whose text is non-empty is a piece of the
    #       answer → yield a "token" event. Chunks that only carry tool-call
    #       deltas have empty text — skip them, never emit empty tokens.
    #   Serialize every event with model_dump_json(exclude_none=True) + "\n".
    #
    # TODO(user) 3: after the loop completes, yield the "done" event.
    #
    # TODO(user) 4: wrap the loop so failures become ONE "error" event and the
    #   generator stops — no re-raise, the stream is the only channel left:
    #     - GraphRecursionError → the AnalystLoopOverrun sentence,
    #     - APIStatusError with status 402 → the OutOfCredit sentence,
    #     - anything else → a generic fixed sentence naming only the
    #       exception *type* (the vote path shows why: messages can carry
    #       provider and model text).
    #
    # When this is green, switch /chat in main.py to StreamingResponse
    # (media_type="application/x-ndjson") and delete run_analyst plus its
    # now-dead tests — the invoke path should not survive as a second way
    # to do the same thing.
    raise NotImplementedError


def run_analyst(
    *,
    model: BaseChatModel,
    result: EvaluateResponse,
    thread_id: str,
    message: str,
    checkpointer: BaseCheckpointSaver,
) -> str:
    """Run the agent one turn further and return its answer.

    The agent is rebuilt per request because the tools close over the request's
    test; the *thread* survives in the shared checkpointer, so the rebuilt
    agent resumes the same transcript — including its earlier ToolMessages.
    The step budget is per turn, derived, not tuned: one model-then-tools round
    per available tool (two supersteps each, in langgraph's currency) plus the
    closing model step, plus one — the limit must exceed the steps executed,
    measured: a one-tool round errors at 3 and passes at 4. A model still
    calling tools past the budget is looping, and the budget converts runaway
    spend into a visible failure.
    """
    tools = build_tools(result)
    agent = create_agent(
        model, tools, system_prompt=_SYSTEM_PROMPT, checkpointer=checkpointer
    )
    # 2n + 1 executed steps (n tool rounds + closing answer), +1 because the
    # limit must strictly exceed the steps executed — see the docstring.
    limit = 2 * len(tools) + 2
    try:
        state = agent.invoke(
            {"messages": [HumanMessage(content=message)]},
            {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": limit,
            },
        )
    except GraphRecursionError as error:
        raise AnalystLoopOverrun(
            f"analyst was still calling tools after {limit} steps"
        ) from error
    except APIStatusError as error:
        # A 402 is the account's fault and terminal; fixed text only — the
        # provider's message never travels. Same mapping as the vote path.
        if error.status_code == 402:
            raise OutOfCredit("OpenRouter credit exhausted (402)") from error
        raise
    reply = state["messages"][-1]
    if not isinstance(reply, AIMessage):
        raise RuntimeError(f"agent ended on a {type(reply).__name__}, not an answer")
    return str(reply.content)
