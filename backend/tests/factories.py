"""Shared builders and doubles for pool- and panel-pipeline tests."""

import json
import re
from collections.abc import Iterable, Iterator, Sequence
from typing import Literal

import psycopg
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool

from app.assembly import AssembledPersona
from app.persistence import persist_pool
from app.schemas import (
    BigFive,
    EducationLevel,
    Gender,
    IncomeBand,
    Locale,
    PanelVote,
    PanelVoteOutput,
    Persona,
    RequestedRegion,
    TargetRequest,
    VoterSummary,
)
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
    age: int = 34,
    country: Locale = Locale.US,
    gender: Gender = "female",
    education: EducationLevel = EducationLevel.TERTIARY,
    income_band: IncomeBand = "middle",
) -> PanelVote:
    """A vote for tests about who was on the panel rather than what they
    chose — the demographics are the load-bearing part, the opinion is stub."""
    return PanelVote(
        persona_id=persona_id,
        chosen_variant_id="a",
        reason="stub",
        voter=VoterSummary(
            country=country,
            age=age,
            gender=gender,
            education=education,
            income_band=income_band,
            traits={},
        ),
    )


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


def ndjson_events(lines: Iterable[str]) -> list[dict[str, str]]:
    """Decode a ChatStreamEvent wire transcript, one JSON object per line —
    the reading half of the NDJSON contract, shared by every stream test."""
    return [json.loads(line) for line in lines]


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
        country=country,
        age=age,
        gender=gender,
        income_quintile=income_quintile,
        education=education,
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
    an agent that never answers — which is how the step budget gets tested.
    """

    responses: list[AIMessage]
    seen: list[list[BaseMessage]] = []

    def bind_tools(
        self, tools: Sequence[BaseTool], **kwargs: object
    ) -> "ScriptedChatModel":
        # The binding is observable through the transcript (a real ToolMessage
        # only appears if the agent executed a real tool), so recording the
        # schemas here would duplicate what the tests already prove.
        return self

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
        for part in re.findall(r"\S+\s*", message.text):
            yield ChatGenerationChunk(message=AIMessageChunk(content=part))
