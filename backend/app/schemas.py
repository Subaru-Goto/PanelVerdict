from pydantic import BaseModel, Field
from typing import Literal

from enum import Enum


class TraitLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class BigFive(BaseModel):
    """The five personality domains as sampled z-scores, grouped so callers can
    iterate the traits. The continuous score is the source of truth; `TraitLevel`
    is derived at render via `bucketize` (so cut-offs can change without resampling).
    """

    openness: float  # curiosity, imagination, appetite for novelty vs. convention
    conscientiousness: float  # organization, self-discipline, deliberation
    extraversion: float  # sociability, assertiveness, energy, reward-seeking
    agreeableness: float  # compassion, trust, cooperation, politeness
    neuroticism: float  # negative-emotion proneness; low = stable


# Big Five domain order — matches BigFive's field order above; the sampler and its
# offline norms derivation both order μ/Σ vectors by this.
TRAIT_ORDER = ["O", "C", "E", "A", "N"]


class LeisureCategory(str, Enum):
    """How free time is spent, harmonized so a profile means the same thing in
    every country.

    Granularity is set by the coarsest national taxonomy we have to map onto.
    Only the German mapping is validated so far; whether every category can be
    filled from the US and Japanese surveys is settled when those builders land.
    """

    TV_MEDIA = "tv_media"
    SOCIALIZING = "socializing"
    GAMES = "games"
    SPORTS_EXERCISE = "sports_exercise"
    OUTDOOR_WALKING = "outdoor_walking"
    READING = "reading"
    ARTS_HOBBIES = "arts_hobbies"
    COMPUTER_LEISURE = "computer_leisure"
    GARDENING_PETS = "gardening_pets"
    GOING_OUT = "going_out"
    VOLUNTEERING = "volunteering"


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

# Human-readable country name, shared by every prompt that names the country.
COUNTRY_NAME: dict[Locale, str] = {
    Locale.US: "the United States",
    Locale.JP: "Japan",
    Locale.DE: "Germany",
}


class EducationLevel(str, Enum):
    BELOW_SECONDARY = "below_secondary"  # ISCED 0–2, no secondary completion
    SECONDARY = "secondary"  # ISCED 3–4, secondary done, no university degree
    TERTIARY = "tertiary"  # ISCED 5–8, university degree or higher


class PersonaDemographics(BaseModel):
    """The demographic core a persona is grounded on — what the sampler emits."""

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


class InterestSynthesis(BaseModel):
    """One persona's interests as the LLM returns them (structured output).

    Deliberately permissive — the real gate (count / length / format) is
    `app.interests._validate`, kept as the single tested source of truth so the
    rules live in one place rather than split with this schema.
    """

    interests: list[str]


class PlausibilityScore(BaseModel):
    """A judge's plausibility rating for one persona (G-Eval structured output)."""

    rating: int = Field(ge=1, le=5)
    reason: str


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
