from pydantic import BaseModel, Field
from typing import Literal

from enum import Enum


class TraitLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class BigFive(BaseModel):
    """The five domains as enum buckets derived from the sampled continuous
    scores (001 decision 6). Grouped so callers can iterate the traits.
    """

    openness: TraitLevel  # curiosity, imagination, appetite for novelty vs. convention
    conscientiousness: TraitLevel  # organization, self-discipline, deliberation
    extraversion: TraitLevel  # sociability, assertiveness, energy, reward-seeking
    agreeableness: TraitLevel  # compassion, trust, cooperation, politeness
    neuroticism: TraitLevel  # negative-emotion proneness; low = stable


class Persona(BaseModel):
    """One panelist (001 field set), stored structured — never as free text.

    For the fixed tracer panel these are hardcoded; the real pool (006)
    samples them.
    """

    id: str
    age: int = Field(ge=18, le=100)
    gender: Literal["male", "female"]
    region: str
    income: str
    education: str
    interests: list[str] = Field(min_length=1, max_length=5)
    big_five: BigFive


class PanelVoteOutput(BaseModel):
    """One persona's vote as the LLM returns it.

    The model is BLIND to variant identity — it only sees two neutrally
    labelled options in a (counterbalanced) order and picks by position.
    """

    chosen: Literal["option_1", "option_2"]
    reason: str


class VoteRecord(BaseModel):
    """One vote after the system re-attaches identity (what we'd persist).

    `chosen` (a position) is resolved to `chosen_variant_id` using the
    presentation order the system created for this persona.
    """

    persona_id: str
    test_id: str
    chosen_variant_id: str
    presentation_order: list[str]
    reason: str


class Verdict(BaseModel):
    """Naive count verdict for the tracer (no posterior — that's ticket 009)."""

    counts: dict[str, int]
    total: int
    winner: str
