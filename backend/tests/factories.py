"""Shared builders and doubles for pool- and panel-pipeline tests."""

from collections.abc import Sequence
from typing import Literal

import psycopg
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

from app.assembly import AssembledPersona
from app.persistence import persist_pool
from app.schemas import (
    BigFive,
    EducationLevel,
    Gender,
    Locale,
    PanelVoteOutput,
    Persona,
    RequestedRegion,
    TargetRequest,
)
from app.vote import VoteResponse

DIM = 1536


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

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: object = None,
        **kwargs: object,
    ) -> ChatResult:
        self.seen.append(list(messages))
        message = (
            self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        )
        # A fresh, id-less copy every time: langgraph's add_messages reducer
        # upserts by message id, so returning the same object twice would
        # replace the first occurrence instead of appending a second.
        message = message.model_copy(deep=True, update={"id": None})
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "scripted"
