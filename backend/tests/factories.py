"""Shared builders and doubles for pool- and panel-pipeline tests."""

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Literal, cast, get_args

import httpx
import psycopg
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.runnables import Runnable
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from openai import APIStatusError

from app.assembly import AssembledPersona
from app.config import settings
from app.persistence import persist_pool
from app.roleplay import RefusalClass, RolePlayOutcome, checked_instruction
from app.schemas import (
    INCOME_BAND_QUINTILES,
    MAX_PERSONA_AGE,
    MIN_PERSONA_AGE,
    BigFive,
    EducationLevel,
    EvaluateResponse,
    Gender,
    IncomeBand,
    Locale,
    Notice,
    PanelCounts,
    PanelVote,
    PanelVoteOutput,
    Persona,
    RequestedRegion,
    TargetQuery,
    TargetRequest,
    TraitLevel,
    TraitName,
    TraitRequest,
    VoterSummary,
    VoteTally,
)
from app.verdict import panel_verdict
from app.vote import VoteResponse

DIM = 1536


def pointing(*axes: int) -> list[float]:
    """A vector along one axis, or between two — hand-placed points whose cosine
    order is checkable in your head: same direction (distance 0) beats a 45°
    blend (≈0.29) beats an orthogonal one (1.0)."""
    vector = [0.0] * DIM
    for axis in axes:
        vector[axis] = 1.0
    return vector


class FixedEmbedder:
    """One canned vector for every text — the query half of a search test.
    A real embedding is a paid call, and no agent or endpoint test makes one."""

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector for _ in texts]


def make_panel_vote(
    persona_id: str,
    *,
    chosen: str = "a",
    reason: str = "stub",
    age: int = 34,
    country: Locale = Locale.US,
    gender: Gender = "female",
    education: EducationLevel = EducationLevel.TERTIARY,
    income_band: IncomeBand = "middle",
    traits: dict[TraitName, TraitLevel] | None = None,
) -> PanelVote:
    """One panelist's vote, with both halves overridable: the demographics for
    tests about who the panel was, the choice and reason for tests about what
    it said. Every default is stub so a test varies only what it is about.

    `traits` defaults to all five at the middle level, because a real voter
    always carries all five (`panel.py` buckets every sampled score) — an empty
    dict was a shape no run emits, and the one container `make_report`'s guard
    could not see into (114/#245).
    """
    return PanelVote(
        persona_id=persona_id,
        chosen_variant_id=chosen,
        reason=reason,
        voter=VoterSummary(
            country=country,
            age=age,
            gender=gender,
            education=education,
            income_band=income_band,
            traits=traits
            if traits is not None
            else dict.fromkeys(get_args(TraitName), TraitLevel.MEDIUM),
        ),
    )


def make_report(
    votes: Sequence[PanelVote] | None = None,
    variants: dict[str, str] | None = None,
    **overrides,
) -> dict:
    """A finished run's body, for the tests that hand `/evaluate`'s answer to
    `/chat`. Built through the models and the app's own arithmetic, so it can
    drift in neither shape nor fact — the literal it replaced said `voted: 50`
    beside `votes: []` (114/#245).

    Everything is derived from the votes: the tally counts them, the verdict is
    the pipeline's own `panel_verdict` over that tally, and **the query
    describes the panel these voters are** rather than a fixed target the
    caller's votes could contradict. A caller passing US voters gets a query
    naming the US, because a report claiming a Japan-only panel of Americans is
    a body no run emits — and the analyst is handed both halves together
    (`analyst.analysis_facts`).

    Every container carries a representative element, since an empty one is
    exactly what let an element-type change validate unnoticed. `**overrides`
    replace whole top-level fields *after* the arithmetic, raw — a test that
    posts a deliberately inconsistent body owns the inconsistency at its own
    call site.
    """
    if votes is None:
        votes = [
            make_panel_vote(f"p-{i}", chosen=chosen, country=Locale.JP)
            for i, chosen in enumerate(("a", "a", "a", "b", "b"), start=1)
        ]
    if not votes:
        raise ValueError(
            "make_report needs at least one vote: an empty panel is the "
            "`voted` beside `votes: []` mismatch this factory exists to "
            "abolish, and it guards no element type. Override the dumped "
            "field if a test means to post one."
        )
    variants = variants or {"a": "Save 50% today", "b": "Limited time: half price"}

    chosen = Counter(vote.chosen_variant_id for vote in votes)
    unknown = sorted(set(chosen) - set(variants))
    if unknown:
        raise ValueError(
            f"votes chose {unknown}, which no variant offers ({sorted(variants)}) "
            "— pass `variants=` for the ones this panel was shown."
        )
    # Zero-filled over the variants, the way `verdict.tally_votes` fills it: a
    # variant nobody chose still reports 0.
    tally = VoteTally(
        counts={variant_id: chosen[variant_id] for variant_id in variants},
        total=len(votes),
    )

    voters = [vote.voter for vote in votes]
    countries = tuple(sorted({voter.country for voter in voters}))
    genders = {voter.gender for voter in voters}
    reading = Notice(
        severity="reading",
        message="Matched against panelists in "
        + ", ".join(country.value for country in countries)
        + ".",
    )
    shortfall = Notice(
        severity="warning",
        message=f"Matched {len(votes)} of the {settings.panel.size} requested.",
    )
    query = TargetQuery(
        countries=countries,
        coverage="requested",
        # The widest range any persona can hold, so no voter falls outside it.
        min_age=MIN_PERSONA_AGE,
        max_age=MAX_PERSONA_AGE,
        # A filter is only named when the whole panel satisfies it: one gender
        # across every voter is a gender the target could have asked for, a mix
        # is not.
        gender=genders.pop() if len(genders) == 1 else None,
        income_quintiles=tuple(
            sorted(
                {
                    quintile
                    for voter in voters
                    for quintile in INCOME_BAND_QUINTILES[voter.income_band]
                }
            )
        ),
        education=tuple(sorted({voter.education for voter in voters})),
        traits=_shared_traits(voters),
        notices=(reading,),
    )
    report = EvaluateResponse(
        verdict=panel_verdict(preferring_b=chosen["b"], total=tally.total),
        tally=tally,
        counts=PanelCounts(
            requested=settings.panel.size, matched=len(votes), voted=len(votes)
        ),
        query=query,
        notices=(reading, shortfall),
        stop_reason="decisive",
        variants=variants,
        votes=list(votes),
    )
    return report.model_dump(mode="json") | dict(overrides)


def _shared_traits(voters: Sequence[VoterSummary]) -> tuple[TraitRequest, ...]:
    """The trait levels the whole panel shares, as the target's own ask.

    A trait request is a filter, so naming one the panel does not satisfy would
    describe a run that could not have happened. One request rather than five:
    the tuple exists so an element-type change has an element to fail on.
    """
    shared = [
        TraitRequest(
            trait=trait, level=level, source_phrase="read from the audience description"
        )
        for trait in get_args(TraitName)
        if len({voter.traits.get(trait) for voter in voters}) == 1
        and (level := voters[0].traits.get(trait)) is not None
    ]
    return tuple(shared[:1])


def tool_call_message(
    name: str = "analyze_results", args: dict[str, str] | None = None
) -> AIMessage:
    """A scripted model turn that calls one tool — the shape every agent and
    endpoint test scripts when it wants a tool round."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args or {}, "id": "c1", "type": "tool_call"}
        ],
    )


def ndjson_events(transcript: str | Iterable[str]) -> list[dict[str, str]]:
    """Decode a ChatStreamEvent wire transcript, one JSON object per line —
    the reading half of the NDJSON contract, shared by every stream test.

    Takes the whole transcript (a response body, or the chunks a stream
    yielded) and does its own splitting, on `"\n"` alone: `str.splitlines()`
    also breaks on U+2028, U+2029 and U+0085, which `model_dump_json()` emits
    raw inside strings — so it cuts a JSON string in half mid-event (114/#245).
    Only the writer's own delimiter is a line break here.
    """
    text = transcript if isinstance(transcript, str) else "".join(transcript)
    return [json.loads(line) for line in text.split("\n") if line]


def voted(
    chosen: Literal["option_1", "option_2"] = "option_1", reason: str = "stub"
) -> VoteResponse:
    """A vote with no usage attached, for the doubles that stand in for a model.

    `usage` is left None rather than filled with plausible token counts: a double that
    invents numbers puts unsourced figures where a cost assertion might later read them.
    """
    return VoteResponse(
        output=PanelVoteOutput(chosen=chosen, reason=reason), usage=None
    )


def big_five(**scores: float) -> BigFive:
    """Every trait at the middle bar the ones named, so a test that varies one trait
    is only about that trait — the other four cannot land in a filter by accident."""
    return BigFive(**(dict.fromkeys(BigFive.model_fields, 0.0) | scores))


def make_persona(
    id_: str = "US-00000",
    *,
    country: Locale | str = "US",
    age: int = 34,
    gender: Gender = "female",
    income_quintile: int = 3,
    education: EducationLevel | str = "tertiary",
    big_five: BigFive | None = None,
) -> Persona:
    return Persona(
        id=id_,
        country=Locale(country),
        age=age,
        gender=gender,
        income_quintile=income_quintile,
        education=EducationLevel(education),
        big_five=big_five
        or BigFive(
            openness=0.1,
            conscientiousness=0.2,
            extraversion=-0.3,
            agreeableness=0.4,
            neuroticism=-0.5,
        ),
    )


def make_assembled(
    persona: Persona | None = None, *, embedding: list[float] | None = None
) -> AssembledPersona:
    persona = persona or make_persona()
    return AssembledPersona(persona=persona, summary_embedding=embedding or [0.5] * DIM)


JAPAN_REQUEST = TargetRequest(
    regions=[RequestedRegion(label="Japan", country_code="JP")]
)


class StubTranslator:
    """Returns its canned request whatever the description says — the translation
    step is a paid model call, and no endpoint or pipeline test should make one."""

    def __init__(self, request: TargetRequest = JAPAN_REQUEST) -> None:
        self._request = request

    def translate(self, *, description: str) -> TargetRequest:
        return self._request


def seed_japanese(conn: psycopg.Connection, count: int) -> None:
    """Personas a `JAPAN_REQUEST` target matches, with distinct ages so a test can
    single one out by its rendered prompt. Ages wrap inside the pool's span, so the
    first sixty stay unique — enough for any test that picks one panelist out."""
    persist_pool(
        conn,
        [
            make_assembled(
                make_persona(id_=f"JP-{i:05d}", country="JP", age=30 + i % 60)
            )
            for i in range(count)
        ],
    )


class ScriptedChatModel(BaseChatModel):
    """A tool-calling-capable fake for `create_agent`: pops scripted AIMessages
    in order and records every prompt it was shown.

    The last response repeats forever, so a script ending in a tool call models
    an agent that never answers — which is how the call budget gets tested.
    """

    responses: list[AIMessage]
    seen: list[list[BaseMessage]] = []

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        # The binding is observable through the transcript (a real ToolMessage
        # only appears if the agent executed a real tool), so recording the
        # schemas here would duplicate what the tests already prove.
        return cast(Runnable[LanguageModelInput, AIMessage], self)

    def _next_message(self, messages: list[BaseMessage]) -> AIMessage:
        self.seen.append(list(messages))
        message = (
            self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        )
        # A fresh, id-less copy every time: langgraph's add_messages reducer
        # upserts by message id, so returning the same object twice would
        # replace the first occurrence instead of appending a second.
        return message.model_copy(deep=True, update={"id": None})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> ChatResult:
        return ChatResult(
            generations=[ChatGeneration(message=self._next_message(messages))]
        )

    @property
    def _llm_type(self) -> str:
        return "scripted"


class StreamingScriptedChatModel(ScriptedChatModel):
    """The same script, delivered the way a natively streaming model delivers
    it: an answer as word-sized chunks, a tool call as one chunk.

    A subclass rather than `_stream` on the base, on purpose: the stream
    transport has two wire dialects (whole messages from non-streaming models,
    deltas from streaming ones), and keeping the base fake non-streaming is
    what keeps the whole-message dialect testable at all.
    """

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._next_message(messages)
        if message.tool_calls:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"]),
                            "id": call["id"],
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                        for call in message.tool_calls
                    ],
                )
            )
            return
        # Word-plus-trailing-space pieces, so the joined chunks reproduce the
        # scripted text byte for byte — the invariant the stream tests assert.
        parts = re.findall(r"\S+\s*", message.text)
        for part in parts[:-1]:
            yield ChatGenerationChunk(message=AIMessageChunk(content=part))
        # Usage rides the final chunk, where `stream_usage=True` puts it on a
        # real model — langgraph's v3 mux turns it into the `message-finish`
        # event's `usage` key, which is where production usage actually
        # travels (070/#161, probed live: the whole-message dialect never
        # fires there). `response_metadata` rides the same chunk the same way:
        # the bridge folds it into the finish event's `metadata`, which is
        # where a real model's finish_reason arrives (090/#195).
        if parts:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=parts[-1],
                    usage_metadata=message.usage_metadata,
                    response_metadata=message.response_metadata,
                )
            )


class StubGenerator:
    """A role-play generator with no model behind it.

    `refusals` maps a text to the class it should be refused with; anything else
    is turned into an instruction the same way every time, so a test can tell a
    generated sentence from an edited one by looking at it.
    """

    def __init__(self, refusals: dict[str, RefusalClass] | None = None) -> None:
        self.refusals: dict[str, RefusalClass] = refusals or {}
        self.drafted: list[str] = []
        self.checked: list[str] = []

    def draft(self, *, words: str) -> RolePlayOutcome:
        self.drafted.append(words)
        if words in self.refusals:
            return RolePlayOutcome(instruction="", refusal=self.refusals[words])
        return RolePlayOutcome(instruction=f"You are {words}.")

    def check(self, *, instruction: str) -> RolePlayOutcome:
        self.checked.append(instruction)
        return checked_instruction(instruction, refusal=self.refusals.get(instruction))


def chat_completion(
    request: httpx.Request, content: str, *, finish_reason: str = "stop"
) -> httpx.Response:
    """A canned 200 from a chat-completions endpoint, so a test can drive the
    whole real client stack — SDK parsing included — without a network."""
    return httpx.Response(
        200,
        request=request,
        json={
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


def status_error(status: int) -> APIStatusError:
    """A provider error with a real status, for probing the screening
    classification without a paid call (072/#163)."""
    return APIStatusError(
        "no endpoints",
        response=httpx.Response(status, request=httpx.Request("POST", "http://x")),
        body=None,
    )
