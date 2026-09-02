"""The 'Ask the analyst' agent: LangChain's `create_agent` over our tools.

The LLM decides *when* to call a tool; deterministic code decides *how* — every
number the analyst can cite comes out of `verdict.py`, recomputed from the
tally. Conversation memory is a server-side checkpointer keyed by `thread_id`:
the checkpointed transcript keeps ToolMessages, so a follow-up is answered from
context instead of re-buying tool calls a text-only replay would drop.
The saver lives in Postgres (#144) — main.py's lifespan owns it — so threads
survive restarts and are shared across workers; this module stays
saver-agnostic and takes whatever `BaseCheckpointSaver` it is handed.
"""

import asyncio
import json
import logging
from collections import Counter
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median_low
from typing import get_args, get_type_hints

import anyio
import psycopg
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, hook_config
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError
from openai import APIStatusError
from pydantic import BaseModel

from app.assembly import Embedder
from app.corpus import search_corpus
from app.panel import persona_summary, voter_summary
from app.persistence import nearest_panelists
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
    Persona,
    StopReason,
    TokenEvent,
    ToolEvent,
    VoterSummary,
)
from app.verdict import panel_verdict

logger = logging.getLogger(__name__)

# How many model calls one turn may make — the quantity a reader wants, declared
# instead of computed (052/#149). 5 is what the retired `2 * len(tools) + 2`
# superstep arithmetic allowed at four tools (one model-then-tools round per held
# tool, plus the closing answer), so it ships the same budget in the honest
# currency; 070/#161's measurement says the worst real turn used 3 calls, so the
# headroom is real work, not slack. Deliberately NOT derived from the tool count:
# #175 removes a tool and #124 adds one, and neither event is a decision about
# how much a turn may spend.
CALLS_PER_TURN = 5

# The backstop behind the budget, in langgraph's superstep currency: twice the
# measured cost of a full-budget turn. A budget-ended turn executes 21
# supersteps — the middleware's hooks compile as graph nodes, so a tool round
# costs 4, not the pre-middleware 2 — measured by sweeping `recursion_limit`
# against a never-answering model: errors through 21, first completes at 22
# (three independent runs, 2026-09-02). 2×22 = 44 keeps the designed order —
# budget first (a sentence and `done`), backstop behind it (an error event) —
# with a whole turn's worth of margin, so adding a middleware or a tool cannot
# quietly invert it; a counting bug still dies within ~10 extra model calls,
# each completion-capped. NOT langgraph's default (10007 in the installed
# version): that would let a broken counter buy thousands of calls first.
_BACKSTOP_STEPS = 44

# What the reader gets when the budget ends a turn. Reply text, not an error
# event: the turn ended, the thread survives, and the next question starts
# fresh — an `error` here would read as a failure the reader should retry
# verbatim, which is exactly the wrong advice.
_BUDGET_SENTENCE = (
    "This turn ran out of its model-call budget before finishing an "
    "answer. Ask again with a narrower question."
)


class _BudgetEndsTheTurn(ModelCallLimitMiddleware):
    """`exit_behavior='end'`, but the injected reply is this codebase's own.

    The library ends an over-budget turn by writing its own English into the
    transcript ("Model call limits exceeded: run limit (5/5)") — library
    text, not model text, but the channel discipline here is stricter than
    that: everything on the wire is either the model's streamed answer or a
    fixed sentence this codebase wrote. So the jump is kept and the message
    replaced. The override rides `before_model` because the async wrapper
    (`abefore_model`) delegates to it — pinned by the stream test, which
    would show the library's wording the day that stops being true.

    What the budget counts is model calls and nothing else: one call may fan
    out several tool executions, and `search_personas` buys an embedding per
    execution — spend the edge caps and the completion ceilings bound, not
    this number."""

    def __init__(self, *, run_limit: int) -> None:
        # `exit_behavior` declared, not inherited: the library's default is
        # 'end' today, and 'error' would hand the reader an error event for
        # a turn the ticket says is not an error.
        super().__init__(run_limit=run_limit, exit_behavior="end")

    # Re-declared rather than inherited: the base marks its hooks with
    # `can_jump_to=["end"]`, and a plain override sheds the marker — today the
    # factory recovers it from the still-decorated `abefore_model`, but that
    # is the library's fallback, not a contract.
    @hook_config(can_jump_to=["end"])
    def before_model(
        self, state: Mapping[str, object], runtime: object
    ) -> dict[str, object] | None:  # type: ignore[override]
        jump = super().before_model(state, runtime)  # type: ignore[arg-type]
        if jump is not None:
            # The one signal an operator gets that the wall was hit: the turn
            # itself ends politely, and the usage log alone would read as an
            # ordinary five-call turn.
            logger.warning(
                "analyst turn ended at its model-call budget (%d calls)",
                self.run_limit,
            )
            jump["messages"] = [AIMessage(content=_BUDGET_SENTENCE)]
        return jump


def _failure_sentence(error: Exception) -> str:
    """The exception *type* is the only part of a failure safe to forward:
    messages can carry provider responses and the model's own output."""
    return f"analyst failed: {type(error).__name__}"


# A constant with zero interpolation, so no request content — not the user's
# words, not the test payload — can reach the instructions that constrain the
# analyst. Everything variable arrives as a ToolMessage the model asked for.
_SYSTEM_PROMPT = (
    "You are PanelVerdict's analyst, and that is the whole of your identity. "
    "You are reading one synthetic-panel A/B test: a panel of sampled, "
    "synthetic personas — not real people — was shown two headline variants and "
    "each cast a forced vote between them.\n"
    "Rules:\n"
    # First, because it is the one question the model will otherwise answer from
    # its own weights: given only a role and no identity, "what are you?" gets
    # the provider's name. That is the largest machinery leak available, and it
    # hands an attacker the model family — injection techniques are family
    # specific. There is nothing to withhold here the way ids or enums could be
    # withheld; the knowledge is in the weights, so this rule is the only lever.
    # Two duties meet in this one rule and they cut in opposite directions: EU
    # AI Act Art. 50(1) requires the ARTIFICIAL NATURE affirmed to anyone who
    # asks, while the leak rule withholds the MAKE. Disclose the kind, never
    # the manufacturer.
    "- You are an AI system, and you say so. Asked what you are, whether you "
    "are human, or who the reader is talking to: you are PanelVerdict's "
    "analyst, an AI system — never a person. What you do not discuss is what "
    "you run on: never name a model, a provider, a company or a version, and "
    "never speculate about them — not even to deny one. If pressed on that, "
    "say that what you run on is not something you discuss and return to the "
    "test.\n"
    # Rewritten by 018/#124. The rule used to send "what does a credible
    # interval mean" to the model's own memory, which is the one place the
    # answer is not: the reader cannot see the code, so a textbook answer about
    # this product is a confident mismatch they have no way to catch. The
    # loophole the original guarded still holds — a question about THIS run goes
    # to a tool, never to the corpus, because the corpus holds no figures.
    "- Three kinds of question, three different rules. Anything about THIS "
    "test — its numbers, its verdict, who voted, how the panel was drawn — "
    "comes from a tool every time: never from memory, never estimated, never "
    "inferred from what you were told earlier in the conversation. Anything "
    "about what this report MEANS or how this product works — what a trait "
    "level says, what the tie zone is, why being ahead is not a clear lead, "
    "whether the panelists are real people, what this method cannot show — "
    "comes from explain_the_report, and you say where it came from: this "
    "product's answers differ from the textbook ones, and the reader cannot "
    "check the code. **Call it even when you think you know the answer.** "
    "Believing you already know is exactly the case it exists for: your own "
    "answer will be the usual one, and the usual one is wrong here often "
    "enough that a reader cannot afford to be guessed at. Anything genuinely "
    "general — how headlines work, what makes copy land — you answer "
    "yourself.\n"
    # 091/#196. The rule above says where each answer comes from, not which
    # questions to take: a curry recipe satisfied every rule and got answered.
    # The line is the product's subject — this test, and how headlines perform
    # in general. The decline has a fixed shape so a judge can score it
    # (experiments/topic_boundary.py) but not fixed words, which would hand a
    # prober a fingerprint of the boundary. Writing headlines is out: the
    # product measures headlines, it does not author them.
    "- Your subject is this test and how headlines perform in general, and "
    "nothing else. Asked for anything outside it — new or better headlines, "
    "other marketing work, the business behind the offer (what to sell, "
    "price, ship or spend on), or any unrelated subject — decline in a fixed "
    "shape: one sentence that names, in your own words, what was asked and "
    "says it is outside what you cover here, then what you can help with — "
    "this test's results, what they mean, and how headlines tend to perform. "
    "Never answer the question first, not even briefly or in part. You "
    "measure headlines; you do not write them — asked for headlines, the "
    "decline points at Test again, which is how new variants get tested.\n"
    "- Compose the two: the concept from explain_the_report, the figures from "
    "analyze_results. The corpus holds no numbers, so a passage never contradicts "
    "this test — and never quote a figure from one.\n"
    "- If a question about this test is one the tools cannot answer, say so "
    "plainly in one sentence. Do not keep calling tools hoping a later one "
    "will cover it.\n"
    # Written after a live reply that said it could not re-run a test, then
    # offered to collect a panel size and country quotas and run one anyway —
    # parameters that never existed. Saying "I cannot" is easy; the failure mode
    # is inventing the shape of the thing you cannot do, so this names the real
    # alternative instead of leaving a blank the model will fill.
    "- You read one finished test. You cannot start another, change who was on "
    "the panel, or alter anything about this one — and you must not offer to, "
    "or ask for details for a run you cannot make. Asked for a new or different "
    "test, say in one sentence that a new test is started from the report "
    "itself, using Test again, and leave it there.\n"
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
# dropped still rates `requested`. The bare enum name read like a verdict
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


def composition_of(people: Sequence[Persona]) -> PanelComposition | None:
    """Panel composition read off personas rather than votes.

    Shared with the panel gate (076/#166) so it and the report use the same
    words for the same panel.
    """
    return _composition_of_voters([voter_summary(person) for person in people])


def _composition(votes: Sequence[PanelVote]) -> PanelComposition | None:
    return _composition_of_voters([vote.voter for vote in votes])


def _composition_of_voters(voters: Sequence[VoterSummary]) -> PanelComposition | None:
    if not voters:
        return None
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
        # Backend-composed sentences — but not free of model text, which the previous
        # wording here claimed. A notice quotes the phrase the translator read a value
        # from ("young", "cautious"), and `unmapped` carries the customer's own words
        # verbatim, so a fragment of both travels in this list.
        #
        # Still safe to forward, for a reason that does not depend on the content: the
        # whole `EvaluateResponse` arrives from the client, so a caller who wanted
        # arbitrary text in here could put it there directly. Nothing is conceded by
        # passing it on, and it reaches the model as a JSON tool result rather than as
        # instructions.
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
    other tool serves recomputed figures or code-composed prose.
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

    One bundle rather than a growing kwargs list: both travel together from the
    request into the closures, and a tool that needs a new runtime dependency
    should have to show up here, visibly.

    It held a translator, a panel model and a panel size until the analyst
    stopped being able to start tests. What is left is what a reader needs: a
    connection and an embedder, neither of which can spend anything.
    """

    conn: psycopg.AsyncConnection
    embedder: Embedder


def build_tools(result: EvaluateResponse, deps: ToolDeps) -> list[BaseTool]:
    """The tools for one request, closed over that request's test.

    Every one of them reads. None of them spends, and none of them writes.

    The analyst used to hold `run_panel_test`, which bought a whole new panel,
    and that made it the only path by which a model could spend money — reached,
    in principle, by a crafted headline becoming a vote reason that
    `read_reasons` hands back. Gating it behind a request field would have
    closed that path; removing the tool deletes it, and there is no flag left
    for a later change to get wrong.

    Nothing is lost, because re-running was never the analyst's job: the report
    has a "Test again" control, and it goes through /evaluate, where the
    screening, the size caps and the delimiting already live.
    """

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
    async def search_personas(query: str) -> str:
        """Individual panelists of THIS test whose profiles best match a
        plain-language description, nearest first — for characterizing or
        quoting particular people. For the panel's overall make-up call
        analyze_results instead: this returns a handful of profiles, never a
        distribution. The query describes people, not SQL."""
        # The embedding is a model call: to a thread, so a tool cannot stall
        # the loop mid-answer.
        embedding = await asyncio.to_thread(deps.embedder.embed, [query])
        found = await nearest_panelists(
            deps.conn,
            embedding=embedding[0],
            panel_ids=[vote.persona_id for vote in result.votes],
            limit=_SEARCH_LIMIT,
        )
        # Summaries only: a persona id is a database handle, not a name a
        # reader can use. Withheld rather than
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
    async def explain_the_report(question: str) -> str:
        """What something on this report MEANS — a trait, a level, the tie zone,
        the credible interval, why a run stopped early, what the method cannot
        show. Returns passages written for this product, each with a citation to
        show the reader. Call this for any "what is / what does that mean / why
        is it done that way" question, instead of answering from memory: your
        own most likely answer about a credible interval or a trait level is a
        textbook one, and this product's is different. For this test's own
        numbers call analyze_results — this holds no figures at all. An empty
        result means the corpus does not cover it; say so."""
        found = await search_corpus(deps.conn, question, deps.embedder)
        return json.dumps(
            [
                {"citation": passage.citation, "passage": passage.passage}
                for passage in found
            ]
        )

    return [analyze_results, search_personas, read_reasons, explain_the_report]


def checkpointed_models(state: type) -> set[type[BaseModel]]:
    """Every pydantic model reachable from a state schema, nested ones included.

    What the checkpointer serializes is exactly what the state schema reaches,
    and JsonPlusSerializer reconstructs a model by re-importing its class.
    Derived rather than listed because the failure is silent: langgraph answers
    a type it cannot rebuild with a plain dict and a log line, so a missing or
    moved model surfaces later as an AttributeError in whichever node reads the
    field. Tests round-trip each model this finds through the saver's serde.
    """
    found: set[type[BaseModel]] = set()

    def walk(annotation: object) -> None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if annotation in found:
                return
            found.add(annotation)
            for field in annotation.model_fields.values():
                walk(field.annotation)
            return
        # list[X], X | None, Annotated[X, reducer], NotRequired[X] — the
        # wrappers a state field arrives in; the models are always in their
        # arguments.
        for argument in get_args(annotation):
            walk(argument)

    for annotation in get_type_hints(state).values():
        walk(annotation)
    return found


class _TurnUsage:
    """One turn's spend, summed off the usage each model call reports —
    `stream_usage=True` in `analyst_chat_model` is what makes the provider
    say. Same reported-coverage discipline as `vote.total_usage`; a turn
    whose model reported nothing logs nothing rather than invented zeros.

    Tokens only, no cost: langchain's streaming path drops the provider's
    `cost` field before it reaches a chunk's metadata (verified against the
    installed package — `token_usage` is set only on the non-streamed path),
    so a cost column here could only ever log zeros. Money is derived at
    measurement time from these tokens and a dated list price (070/#161).
    """

    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens = 0
        self.cached_reported = 0
        self.reasoning_tokens = 0
        self.reasoning_reported = 0

    def take(self, usage: Mapping[str, object] | None) -> None:
        if usage is None:
            return
        self.calls += 1
        self.input_tokens += usage["input_tokens"]
        self.output_tokens += usage["output_tokens"]
        cached = usage.get("input_token_details", {}).get("cache_read")
        if cached is not None:
            self.cached_tokens += cached
            self.cached_reported += 1
        reasoning = usage.get("output_token_details", {}).get("reasoning")
        if reasoning is not None:
            self.reasoning_tokens += reasoning
            self.reasoning_reported += 1

    def log(self, thread_id: str) -> None:
        if self.calls == 0:
            return
        logger.info(
            "analyst usage thread_id=%s: calls=%d input_tokens=%d"
            " cached_tokens=%d/%d output_tokens=%d reasoning_tokens=%d/%d",
            thread_id,
            self.calls,
            self.input_tokens,
            self.cached_tokens,
            self.cached_reported,
            self.output_tokens,
            self.reasoning_tokens,
            self.reasoning_reported,
        )


async def stream_analyst(
    *,
    model: BaseChatModel,
    result: EvaluateResponse,
    thread_id: str,
    message: str,
    checkpointer: BaseCheckpointSaver,
    deps: ToolDeps,
) -> AsyncIterator[str]:
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

    # The budget is per run, deliberately without a `thread_limit`: the
    # conversation ceiling this ticket once named a gap is owned at the HTTP
    # edge now (045's per-thread and per-caller daily turn caps, charged by
    # 089 before the stream exists), where it can refuse with a status code.
    # A second, middleware-kept thread count would double-gate the same thing
    # and disagree with the ledger about when a day resets. Know before
    # flipping that judgment: the middleware still checkpoints a lifetime
    # `thread_model_call_count`, so a `thread_limit` added later would find
    # every surviving thread already over it and lock them all to the budget
    # sentence at their first turn.
    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=[_BudgetEndsTheTurn(run_limit=CALLS_PER_TURN)],
    )

    def line(event: ChatStreamEvent) -> str:
        return event.model_dump_json() + "\n"

    usage = _TurnUsage()
    # Whether the turn's LAST completion with a stated finish_reason ended
    # "length" — ANALYST_MAX_COMPLETION_TOKENS was hit (090/#195). Last, not
    # any: an early cut tool call the model recovered from must not end a
    # whole answer with the cut sentence. The cut text has already streamed
    # by the time this is known, so a truncated turn must not end as if it
    # were whole: the fixed sentence below replaces `done`.
    truncated = False

    try:
        stream = await agent.astream_events(
            {"messages": [HumanMessage(content=message)]},
            {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": _BACKSTOP_STEPS,
            },
            version="v3",
        )
        # Pulled through a task behind `asyncio.shield`, not a plain
        # `async for`, and closed by hand in a shield rather than by
        # `async with` — because of who cancels this generator and how. A
        # reader's disconnect is an anyio task-group cancellation (Starlette's
        # response plumbing), and anyio re-delivers that cancellation at every
        # await until its scope closes. A plain pull puts langgraph's own
        # frames on this task's await chain, so the disconnect unwound the run
        # stream from the inside and re-cancelled langgraph's teardown halfway:
        # the model task kept running with no reader. Measured (113/#243): a
        # single raw `task.cancel()` closes the run cleanly; the same cancel
        # from an anyio group leaks it. The task keeps langgraph's frames off
        # this one — the disconnect lands on the shield instead — and cleanup
        # then delivers at most one raw cancel into the pull and finishes
        # `abort()` behind a shield of its own — `abort()` is verbatim what the
        # manager form runs (`AsyncGraphRunStream.__aexit__` is one line,
        # `await self.abort()`, langgraph 1.x run_stream.py) and its docstring
        # declares it idempotent, so a turn that ends normally pays one no-op
        # call. `GeneratorExit` and `CancelledError` are
        # `BaseException`s, so the broad `except Exception` below sees neither.
        events = stream.__aiter__()
        pull: asyncio.Task | None = None
        try:
            while True:
                pull = asyncio.ensure_future(events.__anext__())
                try:
                    event = await asyncio.shield(pull)
                except StopAsyncIteration:
                    break
                pull = None
                data = event["params"]["data"]
                if event["method"] == "tools" and data.get("event") == "tool-started":
                    yield line(ToolEvent(name=data["tool_name"]))
                elif event["method"] == "messages":
                    payload = data[0] if isinstance(data, tuple) else data

                    if isinstance(payload, AIMessage):
                        usage.take(payload.usage_metadata)
                        reason = (payload.response_metadata or {}).get("finish_reason")
                        if reason is not None:
                            truncated = reason == "length"
                        if payload.text:
                            yield line(TokenEvent(text=payload.text))
                    elif (
                        isinstance(payload, dict)
                        and payload.get("event") == "content-block-delta"
                    ):
                        delta = payload.get("delta", {})
                        if delta.get("type") == "text-delta" and delta.get("text"):
                            yield line(TokenEvent(text=delta["text"]))
                    elif (
                        isinstance(payload, dict)
                        and payload.get("event") == "message-finish"
                    ):
                        # Where a natively streaming model's usage actually
                        # arrives (probed live, 070/#161): the v3 mux folds
                        # the final chunk's usage_metadata into this event.
                        raw = payload.get("usage")
                        usage.take(raw if isinstance(raw, dict) else None)
                        # And where its finish_reason arrives: the bridge
                        # passes the chunks' response_metadata through as
                        # this event's `metadata`.
                        metadata = payload.get("metadata")
                        if isinstance(metadata, dict):
                            reason = metadata.get("finish_reason")
                            if reason is not None:
                                truncated = reason == "length"
        finally:
            with anyio.CancelScope(shield=True):
                if pull is not None and not pull.done():
                    pull.cancel()
                    try:
                        await pull
                    except (asyncio.CancelledError, Exception):
                        # The pull's own cancellation — or its last-instant
                        # error, already surfaced through the shield above.
                        # The pair langgraph's own `abort()` swallows here,
                        # and like it, deliberately not SystemExit.
                        pass
                await stream.abort()
        if truncated:
            # Fixed text, terminal like every error here: a `done` after a cut
            # answer would let the client file the fragment as a whole one.
            yield line(
                ErrorEvent(
                    message="the answer hit the analyst's length ceiling and "
                    "was cut off — ask a narrower question"
                )
            )
            return
    except GraphRecursionError:
        yield line(
            ErrorEvent(
                message=f"analyst was still calling tools after {_BACKSTOP_STEPS} steps"
            )
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
    finally:
        # A `finally`, not per-exit calls: the likely early end of a turn is
        # a reader disconnect, which arrives as GeneratorExit — no `except`
        # sees it. Logging never awaits, so it is safe mid-cancellation.
        usage.log(thread_id)
    yield line(DoneEvent())
