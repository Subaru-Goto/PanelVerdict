"""Shared builders for pool-pipeline tests (personas + assembled personas)."""

from app.assembly import AssembledPersona
from app.schemas import BigFive, Persona

DIM = 1536


def make_persona(id_: str = "US-00000") -> Persona:
    return Persona(
        id=id_,
        country="US",
        age=34,
        gender="female",
        income_quintile=3,
        education="tertiary",
        big_five=BigFive(
            openness=0.1,
            conscientiousness=0.2,
            extraversion=-0.3,
            agreeableness=0.4,
            neuroticism=-0.5,
        ),
    )


def make_assembled(persona: Persona | None = None) -> AssembledPersona:
    persona = persona or make_persona()
    return AssembledPersona(persona=persona, summary_vector=[0.5] * DIM)
