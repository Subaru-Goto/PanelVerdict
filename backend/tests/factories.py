"""Shared builders for pool-pipeline tests (personas + assembled personas)."""

from app.assembly import AssembledPersona
from app.schemas import BigFive, Persona

DIM = 1536


def make_persona(id_: str = "US-00000", interests=("hiking", "jazz")) -> Persona:
    return Persona(
        id=id_,
        country="US",
        age=34,
        gender="female",
        income_quintile=3,
        education="tertiary",
        interests=list(interests),
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
    vectors = [[float(i)] * DIM for i in range(len(persona.interests))]
    return AssembledPersona(persona=persona, interest_vectors=vectors)
