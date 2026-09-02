from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TraitLevel(str, Enum):
    """Rendered intensity of one sampled trait score, ordered low to high.

    Five levels rather than three because three cannot express the continuous
    score the sampler draws: a z of 0.51 and a z of 2.3 would render identically,
    which both flattens the vote prompt and leaves retrieval unable to rank within
    a bucket, one half-sigma wide (docs/research/persona-seed-data.md).
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
    master seed: the database is a cache of that function, not a system
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


class VoterSummary(BaseModel):
    """The voter as a person: demographics verbatim, traits as rendered levels.

    What makes a reason worth reading is who gives it. Trait scores travel
    as `TraitLevel`s, not z-scores, and income as the band, not the quintile —
    both are the words the vote prompt was rendered from, so what the report
    shows about a voter cannot drift from what the panelist enacted.

    Every voter is synthetic — a sampled persona, not a person.
    """

    country: Locale
    age: int
    gender: Gender
    education: EducationLevel
    income_band: IncomeBand
    traits: dict[TraitName, TraitLevel]


class PanelVote(BaseModel):
    """One vote as the report shows it: the choice, the reason, and who gave it.

    Deliberately not `VoteRecord`, which is the ledger's row: `test_id` and
    `presentation_order` are provenance for replay and belong there, not on the
    wire. `persona_id` stays for reproducibility — the report just stops leading
    with it, because an id identifies a row, not a reader.
    """

    persona_id: str
    chosen_variant_id: str
    reason: str
    voter: VoterSummary


class VoteTally(BaseModel):
    """Descriptive per-variant counts. Deliberately no `winner` field.

    A count leader is not a verdict: it carries no uncertainty, and the tiebreak it
    would need is arbitrary. The decision lives in `PanelVerdict`.
    """

    counts: dict[str, int]
    total: int


RopeVerdict = Literal["decisive", "practical_tie", "undecided"]

# Why a run ended before its panel did. A subset of RopeVerdict on purpose:
# `undecided` is not a reason to stop, it is the reason to keep buying votes.
StopReason = Literal["decisive", "practical_tie"]


class PreferenceExposure(BaseModel):
    """Preference-share points each choice risks, both directions."""

    shipping_a: float
    shipping_b: float


class PreferenceProbability(BaseModel):
    """How likely each variant is to be preferred by more than the band.

    Key `a` is about variant A — unlike `PreferenceExposure`, whose `shipping_*`
    keys survive because that number genuinely is about the shipping decision.
    The differing key sets also guard the units: one is a probability in
    0-1, the other preference-share points, and a reader that formatted 0.95 as
    "95 points" would be off by the width of the whole scale.
    """

    a: float
    b: float


class PanelVerdict(BaseModel):
    """The panel's preference for B as a distribution, and the band's own probabilities.

    `share_preferring_b` is the estimate; `probability_majority_prefers_b` is
    confidence in its direction. They are different questions and move
    independently, which is why neither name is shortened.

    `rope` travels with the verdict rather than being implied: the band encodes what
    difference is worth acting on, which is a product decision rather than a derived
    quantity, so a verdict silent about it could be re-labelled later unnoticed.

    **No field here names a recommendation.** That is derived at render time against a
    threshold the reader can see, because a threshold applied here is one they cannot: the
    same word would stand for everything between a coin flip and a near-certainty.

    `detectable_gap` is the smallest gap this panel size could have called decisive. It is
    what makes a null result readable: a wide interval alone cannot distinguish *"they are
    equivalent"* from *"this panel was too small to tell"*.
    """

    share_preferring_b: float
    probability_majority_prefers_b: float
    credible_interval: tuple[float, float]
    credible_mass: float
    rope: tuple[float, float]
    probability_meaningfully_preferred: PreferenceProbability
    probability_practical_tie: float
    detectable_gap: float | None
    expected_preference_shortfall: PreferenceExposure


class RequestedRegion(BaseModel):
    """A place the target named, recorded as named rather than as we can serve it.

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

    Age, income and education each carry a `*_source_phrase`: the words the value was
    read from, set only when the model judged rather than transcribed. Its presence is
    the only thing that lets `resolve_target` disclose a reading, because that function
    never sees the description and so cannot tell an inferred value from an explicit
    one. No reading is legislated anywhere in this project — the model's is disclosed
    instead, so a reader can disagree with it.
    """

    model_config = ConfigDict(extra="forbid")

    regions: list[RequestedRegion] = []
    # Unbounded on purpose: a target asking for teenagers is clamped to the pool's
    # span and told so, where a validation error would only say the call failed.
    min_age: int | None = Field(default=None, ge=0)
    max_age: int | None = Field(default=None, ge=0)
    age_source_phrase: str | None = None
    gender: Gender | None = None
    income_bands: list[IncomeBand] = []
    # A band covers one or two of five quintiles, so `middle` alone excludes 80%
    # of the pool — which is why the reading is worth disclosing at all.
    income_source_phrase: str | None = None
    education: list[EducationLevel] = []
    education_source_phrase: str | None = None
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


class Notice(BaseModel):
    """One thing the customer has to know about this run.

    Not target-scoped: most notices are about how the target was read, but a failed
    vote produces one too.

    Two severities because they call for different treatment, not different styling:
    `warning` means something the customer asked for did not fully happen — a
    panel other than the one asked for, a report the rail could not keep
    (085/#176) — `reading` means it did and
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
    notices: tuple[Notice, ...]


class PanelCounts(BaseModel):
    """How many personas were asked for, matched, and actually voted.

    Three numbers because each *pair* answers a different question: requested vs
    matched is the target being narrower than the pool, matched vs voted is the model
    failing. Only `voted` carries the verdict — a reader given one count cannot tell a
    thin audience from a bad provider day, and both look like a wide interval.
    """

    requested: int
    matched: int
    voted: int


# PENDING USER SIGN-OFF (not yet approved): a judgement about what the
# product is, not a measurement. A headline is a headline — the placeholders in
# the form run to a few dozen characters — and the cap is a generous multiple
# of that, because
# being slightly too tight refuses a real customer while being slightly too
# loose wastes a few hundred tokens. Nobody has surveyed real submissions, so
# there is no distribution behind these the way there is behind the vote
# timeout.
#
# Size matters more here than in an ordinary API: a headline is rendered into
# every panelist's prompt, so an unbounded field is not one oversized request
# but a whole run of them, and the same text reaches the report, the analyst's
# context and the vote cache key. (The target-description cap retired with the
# field itself — demographics are controls now, 094.)
#
# Only size, not format. The ticket asked for "size/format limits" and format
# is deliberately absent: a headline is free text in any language, so any
# allowlist narrow enough to be worth having would refuse real copy.
MAX_HEADLINE_CHARS = 500
# Signed off 2026-08-26 as a launch value (094/#200); revisiting it with usage
# evidence is 107/#228 — raising is a one-constant change, lowering after launch
# breaks saved inputs, which is why it starts tight.
#
# Tighter than a target description, and for a different reason than size. This
# text is rewritten into one sentence every panelist is told to be, and a pile of
# clauses — "sporty vegan parents who shop online and work night shifts" — makes
# each panelist act all of it at once, degrading the portrayal with every clause.
# So the cap is about how much one identity can carry, not about request size.
#
# 200 is the prototype's figure (`docs/design/prototype.html`), carried over
# rather than derived: what a portrayal can hold before it thins is measurable
# and has not been measured. Flagged as owed on 094 rather than dressed up.
MAX_AUDIENCE_CHARS = 200

# What the rewrite may expand those words into. Derived from the cap above rather
# than chosen: the generator is asked for one or two sentences of second-person
# prose about a person the customer described in at most 200 characters, and twice
# the input is the room that needs.
#
# The two caps must not diverge in the other direction either. The gate shows the
# generated sentence in an *editable* field, so a field that accepted less than the
# generator can produce would let a long draft be displayed and never corrected —
# and the reader would meet a raw validation error instead of a sentence naming the
# remedy. Both ends carry this figure for that reason.
MAX_INSTRUCTION_CHARS = 2 * MAX_AUDIENCE_CHARS
# The analyst's composer. A question is longer than a headline and shorter than
# an essay; the cap exists because this text reaches a model's context and the
# checkpointed transcript, and nothing else bounded it.
MAX_CHAT_MESSAGE_CHARS = 2000


class PanelEdit(BaseModel):
    """The demographic controls: the reading as a human sets it.

    One shape for both doors — the form's controls and the gate's edit — so what
    can be asked for and what can be corrected can never drift apart.

    Narrower than `TargetQuery`, which also carries `coverage` and `notices` —
    the report's account of how the customer's words were read. Those are the
    system's testimony about itself, not a filter. A caller-supplied one would
    falsify the report's provenance and put chosen text in front of the analyst,
    which reads `query` as context.
    """

    model_config = ConfigDict(extra="forbid")

    countries: list[Locale] = []
    min_age: int = Field(
        default=MIN_PERSONA_AGE, ge=MIN_PERSONA_AGE, le=MAX_PERSONA_AGE
    )
    max_age: int = Field(
        default=MAX_PERSONA_AGE, ge=MIN_PERSONA_AGE, le=MAX_PERSONA_AGE
    )
    gender: Gender | None = None
    income_quintiles: list[int] = []
    education: list[EducationLevel] = []
    # No traits: temperament left targeting when the controls arrived (094).
    # It remains the panel's internal diversity, not a thing customers aim.

    @model_validator(mode="after")
    def _ages_in_order(self) -> "PanelEdit":
        """Both ends pass their own bounds, so only the pair can say the range
        is empty by construction. Refused in the contract, before anything is
        charged — the guard TargetRequest carried, kept through the controls."""
        if self.min_age > self.max_age:
            raise ValueError(
                f"the age range is empty: from {self.min_age} to {self.max_age} "
                "— swap the two ends"
            )
        return self


class EvaluateRequest(BaseModel):
    # Forbid, not ignore: the frontend deploys separately, so a stale client can
    # still send the retired `target_description`. Ignoring it would run the
    # whole pool against a target the customer named — a paid run answering a
    # different question than asked. A 422 is the honest window behaviour.
    model_config = ConfigDict(extra="forbid")

    # The demographic controls (094): read straight into SQL, no model involved.
    # The default is the whole pool — leaving every control alone is a real
    # choice, not an omission.
    target: PanelEdit = PanelEdit()
    headline_a: str = Field(min_length=1, max_length=MAX_HEADLINE_CHARS)
    headline_b: str = Field(min_length=1, max_length=MAX_HEADLINE_CHARS)
    # Skip the panel gate: this reading was already approved. Claimed by the
    # client, because only something that showed an approval knows one happened.
    reading_accepted: bool = False
    # Who the readers are, beyond anything the pool can be filtered by. Blank
    # means demographics only, and costs no model call at all.
    audience: str = Field(default="", max_length=MAX_AUDIENCE_CHARS)
    # The run's id, client-minted the way /chat's thread ids are (021/#126):
    # the gate-skip path never pauses, so without this the client finishes a
    # run it could never poll the progress of. Optional — minted when absent.
    # 36 = the length of the uuid4 the client mints (ResumeRequest's bound).
    thread_id: str | None = Field(default=None, min_length=1, max_length=36)
    # The role-play sentence a human already approved. Only meaningful with
    # `reading_accepted`, and required there: see the validator below.
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)

    @model_validator(mode="after")
    def _approval_says_what_was_approved(self) -> "EvaluateRequest":
        """A claim of approval has to name the thing approved.

        `reading_accepted` skips the gate, so nobody sees what the panel is told.
        Without this, an audience on that path would be rewritten afresh — new,
        nondeterministic prose in every panelist's identity, approved by nobody,
        on the one path whose entire claim is that it was already approved.

        Refused in the contract rather than in the handler, so it costs nothing:
        the run's purchase is charged before the handler body runs.
        """
        # Stripped, because whitespace names nothing either — and a blank that
        # got past here would reach the graph as "no instruction yet" and be
        # drafted afresh, which is the one thing this validator exists to stop.
        if (
            self.reading_accepted
            and self.audience.strip()
            and not (self.instruction or "").strip()
        ):
            raise ValueError(
                "a run that skips the gate must carry the instruction that was "
                "approved there"
            )
        return self


class ResumeRequest(BaseModel):
    """A human's answer to the panel gate (076/#166)."""

    # 36 = the length of the uuid4 `/evaluate` mints.
    thread_id: str = Field(min_length=1, max_length=36)
    action: Literal["accept", "adjust"]
    # The edited reading, when adjusting. Re-selects with SQL only — never a
    # second translation, which is paid and could disagree with the edit.
    query: PanelEdit | None = None
    # Corrected headlines, when the reader fixed one mid-gate (077, decided
    # 2026-08-31): the paused thread keeps the text from the first submit, so a
    # resume that could not update it would silently vote the old words. Both
    # or neither — one alone would vote a pair nobody composed — and only
    # `adjust` reads them: the gate never edits the text itself.
    headline_a: str | None = Field(
        default=None, min_length=1, max_length=MAX_HEADLINE_CHARS
    )
    headline_b: str | None = Field(
        default=None, min_length=1, max_length=MAX_HEADLINE_CHARS
    )

    @model_validator(mode="after")
    def _both_headlines_or_neither(self) -> "ResumeRequest":
        if (self.headline_a is None) != (self.headline_b is None):
            raise ValueError(
                "one corrected headline alone would vote half the old submit "
                "— send both headlines, or neither"
            )
        return self

    # The role-play sentence as the reader left it at the gate. None means they
    # did not touch the draft — the case that costs no check, since the draft was
    # already classified when it was written. "" is a real answer meaning
    # "demographics only after all", and is not the same as None.
    instruction: str | None = Field(default=None, max_length=MAX_INSTRUCTION_CHARS)


class ToolEvent(BaseModel):
    """A tool just started — the front edge, so the dock can say what the
    analyst is doing while a minutes-long tool is still running."""

    type: Literal["tool"] = "tool"
    name: str


class TokenEvent(BaseModel):
    """One piece of the answer, in arrival order."""

    type: Literal["token"] = "token"
    text: str


class ErrorEvent(BaseModel):
    """The turn failed, in-band: a stream commits its HTTP status at the
    first byte, so failures cannot become a 502 or 402 after tokens have
    flowed — `message` carries the same fixed sentences a status code used
    to carry, never provider or model text. Terminal: no `done` follows."""

    type: Literal["error"] = "error"
    message: str


class DoneEvent(BaseModel):
    """The stream finished cleanly — what tells the client a completed turn
    from a dropped connection."""

    type: Literal["done"] = "done"


# One NDJSON line of the streaming /chat response. A union, not one
# model with optionals: each event type states the field it must carry, so
# a tool event without a name cannot be constructed, and nothing depends on
# a serialization flag to keep the unused fields off the wire.
ChatStreamEvent = ToolEvent | TokenEvent | ErrorEvent | DoneEvent


class RunUsage(BaseModel):
    """What the run's votes cost, as `total_usage` sums it (070/#161).

    A mirror of `vote.UsageTotals`, field for field, because the honesty
    mechanism lives in the shape: every optional-per-vote figure travels with
    the count of votes that reported it, so a partial sum can never read as a
    total. A fully cached replay honestly reads votes=N, usage_reported=0.

    On the wire and therefore in every kept test's stored report — the
    operator view of the future gets history from day one. Deliberately not
    rendered to the reader (decided 2026-09-02 on the ticket): the customer
    does not pay per run, so cost is operator telemetry, not report content.
    """

    votes: int
    usage_reported: int
    input_tokens: int
    cached_tokens: int
    cached_reported: int
    output_tokens: int
    reasoning_tokens: int
    reasoning_reported: int
    cost: float
    cost_reported: int
    seconds_slowest: float
    seconds_total: float


class EvaluateResponse(BaseModel):
    """One panel test as the report renders it.

    `query` and `notices` overlap — the query carries its own notices — and the
    duplication is accepted: `query` is the filter contract the verdict was drawn
    under, `notices` is the complete reader-facing set including what retrieval
    itself revealed, and a projection type that subtracted one from the other would
    exist only to be re-joined in the UI.

    No `extra="forbid"` here, unlike its siblings, and that is load-bearing: the
    client stores what `/evaluate` answered and forwards it whole to `/chat`, so
    every real turn arrives carrying `CompletedRun`'s `status`. Forbidding extras
    would 402 nothing and 422 every analyst turn. Pinned by
    `test_a_report_the_panel_produced_is_a_report_the_analyst_accepts` (048/#146),
    the one test that posts the body the browser actually sends.
    """

    verdict: PanelVerdict
    tally: VoteTally
    counts: PanelCounts
    query: TargetQuery
    notices: tuple[Notice, ...]
    # An early stop is a fact about the run, carried as data so the report can
    # distinguish "stopped because answered" from a shortfall without parsing prose.
    stop_reason: StopReason | None
    variants: dict[str, str]
    votes: list[PanelVote]
    # None on reports kept before 070 shipped and on demo fixtures captured
    # before it — absent is not zero, the same reading VoteUsage gives it.
    usage: RunUsage | None = None


class ChatRequest(BaseModel):
    """One analyst turn: the new message, the thread it continues, and the test.

    History lives server-side under `thread_id`: the
    checkpointed transcript keeps ToolMessages, so a follow-up is answered from
    context instead of re-buying the tool calls a text-only replay would drop.
    The client mints the id — one per rendered report.

    The whole result still travels rather than a test id, because nothing
    persists a finished test today — the votes ledger stores votes, not
    verdicts. The payload is context, not testimony: every *verdict* number
    the analyst cites is recomputed server-side from the tally
    (`analyst.analysis_facts`). Who the voters were is the one thing that
    cannot be — the panel's demographics are forwarded from `votes[].voter`
    as given, because nothing server-side remembers a finished panel.
    """

    thread_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)
    result: EvaluateResponse
