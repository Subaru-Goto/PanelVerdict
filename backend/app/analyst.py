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
    "- Two kinds of question, two different rules. Anything about THIS test — "
    "its numbers, its verdict, who voted, how the panel was drawn — comes from "
    "a tool every time: never from memory, never estimated, never inferred "
    "from what you were told earlier in the conversation. Anything general — "
    "what a credible interval means, why a headline might land, what this "
    "method can and cannot show — you answer yourself, directly, and do not "
    "reach for a tool at all.\n"
    "- If a question about this test is one the tools cannot answer, say so "
    "plainly in one sentence. Do not keep calling tools hoping a later one "
    "will cover it.\n"
    # Third rather than second-to-last, deliberately: the two rules above are
    # what make machinery salient, so the ban on speaking it belongs against
    # them rather than five rules downstream where it lost in live use.
    "- Answer as an analyst, not as a program. Open with the finding, never "
    "with how you came by it. Never name a tool, a function, a field or a step "
    "you took, never quote a raw value such as null or an internal label, and "
    "never say you are looking something up. If a sentence lets the reader see "
    "there was a program involved, rewrite it — the reader wants the finding, "
    "not the machinery.\n"
    "- The headline number is a preference share of the panel, never a "
    "click-through rate: real readers mostly see one variant, and the panel is "
    "unvalidated where two variants say the same thing differently.\n"
    "- Plain language: prefer 'tie zone' over ROPE and spell out what an "
    "interval means; keep replies to a few sentences.\n"
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


# The clauses are `_stopped_early_notice`'s own, so the analyst and the report
# explain a stop the same way. The frame deliberately is not: that notice may
# say panelists went unpolled because the pipeline knows how many it asked,
# while an EvaluateResponse carries no `asked` — and a stop firing on the last
# chunk leaves nobody unpolled. Hence "stopped once", never "stopped early".
_POLLING: dict[StopReason | None, str] = {
    None: "Polling ran through every matched panelist.",
    "decisive": "Polling stopped once the panel had already decided.",
    "practical_tie": (
        "Polling stopped once the difference was already credibly too small to matter."
    ),
}


# Every rung speaks about *places* and nothing else — `_resolve_regions` sets
# it from regions alone, so a target whose age or personality was quietly
# dropped still rates `requested` (024). The bare enum name read like a verdict
# on the whole target, and in live use it was cited as one; the sentences and
# the field name both narrow it back to what it actually claims. `requested` is
# phrased as a substitution that didn't happen, since no region named is also
# `requested` and "every place was matched" would imply places were named.
_REGION_MATCH: dict[CoverageRung, str] = {
    "requested": "No place the target named had to be substituted.",
    "approximated": (
        "At least one place the target named was served by a stand-in region; "
        "a notice names which."
    ),
    "unmatched": (
        "No place the target named could be matched: the panel spans the whole "
        "pool and carries no geographic targeting."
    ),
}


class AnalysisFacts(BaseModel):
    """What `analyze_results` hands the model, spelled out rather than a loose
    dict — the shape is the tool's contract with the prompt.

    `polling` is a sentence rather than the `stop_reason` enum it replaces.
    A value of `null` has no sayable form, and the payload composed no English
    about it, so the model quoted the field name at the reader — machinery the
    prompt forbids but the tool supplied. Withheld beats forbidden, the same
    move that took persona ids off `search_personas`. `region_match` replaces
    the `coverage` rung for the same reason, plus one of its own: the enum name
    read like a verdict on the whole target when it only ever spoke of places.
    """

    variants: dict[str, str]
    tally: dict[str, int]
    counts: PanelCounts
    polling: str
    region_match: str
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
        polling=_POLLING[result.stop_reason],
        region_match=_REGION_MATCH[result.query.coverage],
        # Backend-composed sentences (never provider text), so safe to forward.
        notices=[notice.message for notice in result.notices],
        panel=_composition(result.votes),
        verdict=panel_verdict(preferring_b=counts["b"], total=result.tally.total),
    )


class ChosenReasons(BaseModel):
    """One headline and the words the panelists who picked it gave for it."""

    headline: str
    reasons: list[str]


def vote_reasons(result: EvaluateResponse) -> dict[str, ChosenReasons]:
    """What the panel said, grouped by what it chose.

    Keyed on every variant rather than only the ones with votes: "nobody said
    anything for A" is a finding, and a missing key reads as a tool that failed
    to report rather than a headline nobody picked.

    This is the first thing the analyst reads that another model wrote — every
    other tool serves recomputed figures or code-composed prose. See 029 for
    where that boundary now sits.
    """
    return {
        variant_id: ChosenReasons(
            headline=headline,
            reasons=[
                vote.reason
                for vote in result.votes
                if vote.chosen_variant_id == variant_id
            ],
        )
        for variant_id, headline in result.variants.items()
    }


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
        """Every number and every count for this test — but not a word anyone
        said, which is read_reasons. The verdict recomputed from the
        vote tally, plus counts, how far polling ran, how the places named in
        the target were matched, and notices — and who the panel was, as the
        voters' age range and their spread across country, gender, education
        and income. Call this before citing any figure, and to answer anything
        about the panel's make-up or whether it matched the audience that was
        asked for. Its wording is already reader-facing: say it, don't decode
        it."""
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
    def read_reasons() -> str:
        """What the panelists actually said, in their own words, grouped by the
        headline each of them chose. Call this for anything about WHY the panel
        leaned the way it did, what appealed about a headline, or to summarise
        the reasoning: analyze_results holds the numbers, this holds the words,
        and no other tool carries a reason at all."""
        return json.dumps(
            {
                variant_id: chosen.model_dump()
                for variant_id, chosen in vote_reasons(result).items()
            }
        )

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
            polling=_POLLING[run.stop_reason],
            region_match=_REGION_MATCH[run.selection.query.coverage],
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

    return [analyze_results, search_personas, read_reasons, run_panel_test]


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
