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

import json
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from statistics import median_low

import psycopg
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError
from openai import APIStatusError
from pydantic import BaseModel

from app import pipeline
from app.assembly import Embedder
from app.panel import persona_summary, votes_with_voters
from app.persistence import nearest_panelists
from app.pipeline import EmptyPanel, NoVotes
from app.schemas import (
    ChatStreamEvent,
    CoverageRung,
    DoneEvent,
    EducationLevel,
    ErrorEvent,
    EvaluateResponse,
    Gender,
    IncomeBand,
    Locale,
    PanelCounts,
    PanelVerdict,
    PanelVote,
    StopReason,
    TokenEvent,
    ToolEvent,
)
from app.targeting import TargetTranslator
from app.verdict import panel_verdict
from app.vote import OutOfCredit, PanelLLM


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
    "interval means; keep replies to a few sentences.\n"
    "- Answer as an analyst, not as a program: never name a tool, a function, "
    "a field or a step you took, and never say you are looking something up. "
    "The reader wants the finding, not the machinery.\n"
    "- Describe panelists as people — their age, country and circumstances. "
    "Never quote an id or any other internal handle."
)


class PanelComposition(BaseModel):
    """Who voted, counted from the votes themselves.

    Deliberately carries no total: `counts.voted` already says how many, and a
    second count recomputed from a different field of the same request would
    put two disagreeing answers in one payload with no rule for which to cite.
    This says who they were, which is what can answer why a target's panel
    looks wrong.
    """

    age_min: int
    age_median: int
    age_max: int
    countries: dict[Locale, int]
    genders: dict[Gender, int]
    education_levels: dict[EducationLevel, int]
    income_bands: dict[IncomeBand, int]


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
    # None when the request carried no votes: an age range of 0–0 would be a
    # claim about a panel that isn't there.
    panel: PanelComposition | None


def _grouped[Attribute: str](values: Iterable[Attribute]) -> dict[Attribute, int]:
    """Counts, biggest group first so the panel's shape reads in order; ties
    break on the name, so the same panel always renders identically.

    Generic rather than `dict[str, int]`: the keys stay the enums and literals
    the voter carries, so a mistyped attribute is a type error here rather
    than a silently empty group on the wire. The `str` bound is load-bearing,
    not decoration — the tie-break compares keys, which a bare Enum refuses.
    """
    counts = Counter(values)
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def _composition(votes: Sequence[PanelVote]) -> PanelComposition | None:
    if not votes:
        return None
    voters = [vote.voter for vote in votes]
    ages = sorted(voter.age for voter in voters)
    return PanelComposition(
        age_min=ages[0],
        # median_low, not median: an even panel has no middle voter, and half
        # a year of age would be a number no panelist could be asked about.
        age_median=median_low(ages),
        age_max=ages[-1],
        countries=_grouped(voter.country for voter in voters),
        genders=_grouped(voter.gender for voter in voters),
        education_levels=_grouped(voter.education for voter in voters),
        income_bands=_grouped(voter.income_band for voter in voters),
    )


def analysis_facts(result: EvaluateResponse) -> AnalysisFacts:
    """The current test as the analyst may cite it.

    Every *verdict* figure is recomputed rather than read off the request, so
    a client that doctored those fields cannot make the analyst repeat them.
    The panel's composition is the one part that cannot be recomputed — who
    voted is only knowable from the votes the request carries.
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
        panel=_composition(result.votes),
        verdict=panel_verdict(preferring_b=counts["b"], total=result.tally.total),
    )


# Top-5 per search: user sign-off 2026-07-29, convention rather than
# measurement — ~40 tokens per summary keeps one search near 200 tokens while
# giving the model enough names to answer concretely.
_SEARCH_LIMIT = 5


@dataclass(frozen=True)
class ToolDeps:
    """Everything the tools need at call time that is not the test itself.

    One bundle rather than a growing kwargs list: these five always travel
    together from the request into the closures, and a tool that needs a new
    runtime dependency should have to show up here, visibly.
    """

    conn: psycopg.Connection
    embedder: Embedder
    translator: TargetTranslator
    panel_llm: PanelLLM
    panel_size: int


def build_tools(result: EvaluateResponse, deps: ToolDeps) -> list[BaseTool]:
    """The tools for one request, closed over that request's test."""

    @tool
    def analyze_results() -> str:
        """Everything known about this test: the verdict recomputed from the
        vote tally, plus counts, stop reason, coverage and notices — and who
        the panel was, as the voters' age range and their spread across
        country, gender, education and income. Call this before citing any
        figure, and to answer anything about the panel's make-up or whether
        it matched the audience that was asked for."""
        return analysis_facts(result).model_dump_json()

    @tool
    def search_personas(query: str) -> str:
        """Individual panelists of THIS test whose profiles best match a
        plain-language description, nearest first — for characterizing or
        quoting particular people. For the panel's overall make-up call
        analyze_results instead: this returns a handful of profiles, never a
        distribution. The query describes people, not SQL."""
        found = nearest_panelists(
            deps.conn,
            embedding=deps.embedder.embed([query])[0],
            panel_ids=[vote.persona_id for vote in result.votes],
            limit=_SEARCH_LIMIT,
        )
        # Summaries only: a persona id is a database handle, not a name a
        # reader can use (023's ruling for the report). Withheld rather than
        # forbidden — the model cannot quote what it was never given.
        return json.dumps([persona_summary(persona) for persona in found])

    @tool
    def run_panel_test(target_description: str) -> str:
        """Run this test's two headlines against a NEW panel drawn from a
        different target audience. This spends real money — one paid model
        vote per matched panelist — so call it only when the user explicitly
        asks to test another audience or run the test again. Returns the new
        run's numbers in the same shape analyze_results reports; the original
        test's numbers stay with analyze_results."""
        try:
            run = pipeline.run_panel_test(
                deps.conn,
                description=target_description,
                variants=result.variants,
                size=deps.panel_size,
                translator=deps.translator,
                llm=deps.panel_llm,
            )
        except (EmptyPanel, NoVotes) as error:
            # Both sentences are this codebase's own (the /evaluate handlers
            # forward them for the same reason), and a failed re-test should
            # end as an answer, not kill the turn.
            return json.dumps({"error": str(error)})
        facts = AnalysisFacts(
            variants=result.variants,
            tally=run.tally.counts,
            counts=run.counts,
            stop_reason=run.stop_reason,
            coverage=run.selection.query.coverage,
            notices=[notice.message for notice in run.notices],
            # Trusted as-is: this verdict came out of our own pipeline one
            # line up, unlike the request's, which analysis_facts recomputes.
            verdict=run.verdict,
            # The same voter join the report does — a fresh run's panel is as
            # describable as the original's, which is what lets the model
            # compare the two audiences rather than just their numbers.
            panel=_composition(
                votes_with_voters(run.votes.records, run.selection.panel)
            ),
        )
        return json.dumps(
            {
                "target_description": target_description,
                "facts": facts.model_dump(mode="json"),
            }
        )

    return [analyze_results, search_personas, run_panel_test]


def stream_analyst(
    *,
    model: BaseChatModel,
    result: EvaluateResponse,
    thread_id: str,
    message: str,
    checkpointer: BaseCheckpointSaver,
    deps: ToolDeps,
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
    tools = build_tools(result, deps)

    # The step budget, per turn, derived not tuned: one model-then-tools round
    # per available tool (two supersteps each, in langgraph's currency) plus
    # the closing model step, plus one — the limit must strictly exceed the
    # steps executed, measured: a one-tool round errors at 3 and passes at 4.
    # A model still calling tools past the budget is looping, and the budget
    # converts runaway spend into a visible failure. Note what the cap now
    # admits: up to three tool rounds may each be a run_panel_test — a full
    # paid panel run — so the budget is a tripwire, not the spend gate; the
    # gate is the tool description's only-on-explicit-ask rule plus 012c's UI.
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
    except OutOfCredit as error:
        # The pipeline's own sentence, never the provider's (main.py's 402
        # handler forwards it for the same reason) — it names the remedy,
        # which "analyst failed: OutOfCredit" would throw away.
        yield line(ErrorEvent(message=str(error)))
        return
    except Exception as error:
        # Broad on purpose — the stream is the only channel left.
        yield line(ErrorEvent(message=_failure_sentence(error)))
        return
    yield line(DoneEvent())
