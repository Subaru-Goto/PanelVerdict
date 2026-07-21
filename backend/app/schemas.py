from pydantic import BaseModel, Field
from typing import Literal

from enum import Enum


class TraitLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class BigFive(BaseModel):
    """The five personality domains as level buckets, grouped into one type so
    callers can iterate the traits.
    """

    openness: TraitLevel  # curiosity, imagination, appetite for novelty vs. convention
    conscientiousness: TraitLevel  # organization, self-discipline, deliberation
    extraversion: TraitLevel  # sociability, assertiveness, energy, reward-seeking
    agreeableness: TraitLevel  # compassion, trust, cooperation, politeness
    neuroticism: TraitLevel  # negative-emotion proneness; low = stable


class Locale(str, Enum):
    US = "US"
    JP = "JP"
    DE = "DE"


class CultureTag(str, Enum):
    WESTERN = "western"
    ASIAN = "asian"


# Coarse targeting bucket, derived from country — never stored on a Persona.
COUNTRY_CULTURE_TAG: dict[Locale, CultureTag] = {
    Locale.US: CultureTag.WESTERN,
    Locale.DE: CultureTag.WESTERN,
    Locale.JP: CultureTag.ASIAN,
}


class EducationLevel(str, Enum):
    BELOW_SECONDARY = "below_secondary"  # ISCED 0–2, no secondary completion
    SECONDARY = "secondary"  # ISCED 3–4, secondary done, no university degree
    TERTIARY = "tertiary"  # ISCED 5–8, university degree or higher


class PersonaDemographics(BaseModel):
    """The demographic core a persona is grounded on — what the 006b sampler emits.

    Big Five (006c) and interests (006d) are added later; `Persona` extends this.
    """

    country: Locale
    age: int = Field(ge=18, le=100)
    gender: Literal["male", "female"]
    income_quintile: int = Field(ge=1, le=5)  # within-country income rank band
    education: EducationLevel


class Persona(PersonaDemographics):
    """One panelist, stored as structured typed fields (never free text)."""

    id: str
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
    """Naive vote-count verdict: per-variant counts, total, and the winner."""

    counts: dict[str, int]
    total: int
    winner: str


class EvaluateRequest(BaseModel):
    headline_a: str
    headline_b: str


class EvaluateResponse(BaseModel):
    verdict: Verdict
    variants: dict[str, str]
    votes: list[VoteRecord]
