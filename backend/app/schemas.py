from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from enum import Enum


class TraitLevel(str, Enum):
    """Rendered intensity of one sampled trait score, ordered low to high.

    Five levels rather than three because three cannot express the continuous
    score the sampler draws: a z of 0.51 and a z of 2.3 would render identically,
    which both flattens the vote prompt and leaves retrieval unable to rank within
    a bucket (006j D1b).
    """

    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


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
    """One panelist, stored as structured typed fields — no free text at all.

    Every field is sampled or derived, so a persona is a pure function of the
    master seed (006j): the database is a cache of that function, not a system
    of record.

    `extra="forbid"` because pydantic's default would silently swallow a field
    that no longer exists — dropping `interests` left a caller still passing it
    and the whole suite stayed green.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    big_five: BigFive


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


class VoteTally(BaseModel):
    """Descriptive per-variant counts. Deliberately no `winner` field.

    A count leader is not a verdict: it carries no uncertainty, and the tiebreak it
    would need is arbitrary. The decision lives in `PanelVerdict`.
    """

    counts: dict[str, int]
    total: int


RopeVerdict = Literal["decisive", "practical_tie", "undecided"]


class PreferenceExposure(BaseModel):
    """Preference-share points each choice risks, both directions."""

    shipping_a: float
    shipping_b: float


class PanelVerdict(BaseModel):
    """The panel's preference for B as a distribution, plus a decision about it.

    `share_preferring_b` is the estimate; `probability_majority_prefers_b` is
    confidence in its direction. They are different questions and move
    independently, which is why neither name is shortened.

    `rope` travels with the verdict rather than being implied: the band encodes what
    difference is worth acting on, which is a product decision rather than a derived
    quantity, so a verdict silent about it could be re-labelled later unnoticed.

    None of these are click-through rates. The panel chose *between* two variants;
    real readers mostly see one.
    """

    share_preferring_b: float
    probability_majority_prefers_b: float
    credible_interval: tuple[float, float]
    credible_mass: float
    rope: tuple[float, float]
    outcome: RopeVerdict
    expected_preference_shortfall: PreferenceExposure


class EvaluateRequest(BaseModel):
    headline_a: str
    headline_b: str


class EvaluateResponse(BaseModel):
    verdict: PanelVerdict
    tally: VoteTally
    variants: dict[str, str]
    votes: list[VoteRecord]
