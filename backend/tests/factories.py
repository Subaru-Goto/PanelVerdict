"""Shared builders for pool-pipeline tests (personas + assembled personas)."""

from typing import Literal

from app.assembly import AssembledPersona
from app.schemas import (
    BigFive,
    EducationLevel,
    Gender,
    Locale,
    PanelVoteOutput,
    Persona,
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
