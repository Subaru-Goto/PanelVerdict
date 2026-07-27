from pydantic import BaseModel, ConfigDict, Field, model_validator
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

# Spelled out rather than derived from BigFive's fields, because a Literal cannot be
# built from a runtime tuple and still narrow. A test pins the two together.
TraitName = Literal[
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
]


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


Gender = Literal["male", "female"]

# The pool's age span. Named because a target asking outside it has to be clamped
# and told, which needs the bound as a value rather than as a Field constraint.
MIN_PERSONA_AGE = 18
MAX_PERSONA_AGE = 100

IncomeBand = Literal["lower", "middle", "upper"]

# Income is a within-country quintile rank; a target speaks in coarse bands. One
# mapping, both directions: `panel` renders a quintile through it and `targeting`
# expands a band back into quintiles, so the words a query is matched on cannot
# drift from the words the persona summary was embedded with.
INCOME_BAND_QUINTILES: dict[IncomeBand, tuple[int, ...]] = {
    "lower": (1, 2),
    "middle": (3,),
    "upper": (4, 5),
}


class PersonaDemographics(BaseModel):
    """The demographic core a persona is grounded on — what the sampler emits."""

    country: Locale
    age: int = Field(ge=MIN_PERSONA_AGE, le=MAX_PERSONA_AGE)
    gender: Gender
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


class RequestedRegion(BaseModel):
    """A place the target named, recorded as named rather than as we can serve it.

    Keeping the requested place separate from the seeded countries is what makes a
    coverage gap visible: a translator that emitted `Locale` would have to answer
    "China" with Japan, and the substitution would be indistinguishable from a
    target that asked for Japan.

    `country_code` is None when the label covers more than one country ("Europe")
    or names none; `culture_tag` is None when the label spans both buckets.
    """

    label: str
    country_code: str | None = None
    culture_tag: CultureTag | None = None


class TraitRequest(BaseModel):
    """One Big Five level read out of the target, and the words it was read from.

    `source_phrase` exists so the reading can be shown back. Mapping "cautious" onto
    a trait is an interpretation, and an interpretation the customer cannot see is
    one they cannot correct.

    Frozen because `TargetQuery` carries these through unchanged and is itself frozen:
    a hashable query needs hashable fields.
    """

    model_config = ConfigDict(frozen=True)

    trait: TraitName
    level: TraitLevel
    source_phrase: str


class TargetRequest(BaseModel):
    """What the translator read out of a natural-language target description.

    Every field is optional and defaults to asking for nothing, because the model
    has to be able to say "these words mapped to nothing" — which is what `unmapped`
    carries. A request is not yet executable: `targeting.resolve_target` applies the
    coverage ladder to it.
    """

    model_config = ConfigDict(extra="forbid")

    regions: list[RequestedRegion] = []
    # Unbounded on purpose: a target asking for teenagers is clamped to the pool's
    # span and told so, where a validation error would only say the call failed.
    min_age: int | None = Field(default=None, ge=0)
    max_age: int | None = Field(default=None, ge=0)
    gender: Gender | None = None
    income_bands: list[IncomeBand] = []
    education: list[EducationLevel] = []
    traits: list[TraitRequest] = []
    unmapped: list[str] = []

    @model_validator(mode="after")
    def _age_range_has_members(self) -> "TargetRequest":
        if (
            self.min_age is not None
            and self.max_age is not None
            and self.min_age > self.max_age
        ):
            raise ValueError(f"empty age range: {self.min_age}-{self.max_age}")
        return self


class TargetNotice(BaseModel):
    """One thing the customer has to know about how their target was read.

    Two severities because they call for different treatment, not different styling:
    `warning` means the panel is not the one asked for, `reading` means it is and
    here is the interpretation it rests on. Collapsing them would bury the
    substitutions among the paraphrases.
    """

    severity: Literal["warning", "reading"]
    message: str


CoverageRung = Literal["requested", "approximated", "unmatched"]


class TargetQuery(BaseModel):
    """A target description as the pool can serve it, plus what that cost.

    Lives here rather than beside `targeting.resolve_target` because it is the
    contract between that resolution and the SQL that executes it — and because the
    report has to show which filters a verdict was drawn under.

    `countries` is always explicit rather than empty-means-unfiltered, so the value
    never has to be read together with something else to know what it means.

    `coverage` is what `countries` cannot say on its own. Two very different targets
    resolve to the whole pool — one that named no country (served exactly) and one
    whose country we could not serve at all (substituted) — so the tuple is identical
    and the meaning is opposite. `requested` means every named place was served, or
    none was named; `approximated` means at least one was served by its
    culture-tag neighbours; `unmatched` means none could be served and the panel is
    the whole pool, carrying no geographic targeting at all.

    `traits` carries the levels themselves rather than prose about them, because they
    become score bounds in SQL and because the report has to be able to show the
    reading a verdict rests on. At most one entry per trait.
    """

    model_config = ConfigDict(frozen=True)

    countries: tuple[Locale, ...]
    coverage: CoverageRung
    min_age: int
    max_age: int
    gender: Gender | None
    income_quintiles: tuple[int, ...]
    education: tuple[EducationLevel, ...]
    traits: tuple[TraitRequest, ...]
    notices: tuple[TargetNotice, ...]


class EvaluateRequest(BaseModel):
    headline_a: str
    headline_b: str


class EvaluateResponse(BaseModel):
    verdict: PanelVerdict
    tally: VoteTally
    variants: dict[str, str]
    votes: list[VoteRecord]
