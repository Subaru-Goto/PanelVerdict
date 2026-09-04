from app.bigfive import bigfive_from_levels, bucketize
from app.schemas import (
    BigFive,
    COUNTRY_NAME,
    EducationLevel,
    INCOME_BAND_QUINTILES,
    PanelVote,
    Persona,
    TraitLevel,
    TraitName,
    VoteRecord,
    VoterSummary,
)

# Five intensities per trait, phrased without pronouns so the vote prompt (second
# person) and the summary embedded for retrieval (third person) can share one
# table — the persona a query matches has to be the persona that votes. Wording
# is BFI-2-Expanded-style descriptions of the sampled level, never numbers.
_TRAIT_PHRASES: dict[TraitName, dict[TraitLevel, str]] = {
    "openness": {
        TraitLevel.VERY_HIGH: "restlessly curious, forever chasing the new and the unconventional",
        TraitLevel.HIGH: "curious and imaginative, drawn to new ideas and experiences",
        TraitLevel.MEDIUM: "open to new ideas but still fond of the tried-and-true",
        TraitLevel.LOW: "practical and conventional, preferring the familiar to the novel",
        TraitLevel.VERY_LOW: "firmly set in familiar ways, with little appetite for anything untried",
    },
    "conscientiousness": {
        TraitLevel.VERY_HIGH: "meticulous and highly disciplined, planning everything down to the detail",
        TraitLevel.HIGH: "organized and self-disciplined, careful to think things through",
        TraitLevel.MEDIUM: "reasonably organized without being rigid about it",
        TraitLevel.LOW: "spontaneous and easygoing, not one to fuss over plans or details",
        TraitLevel.VERY_LOW: "thoroughly unstructured, acting on impulse and leaving plans half-made",
    },
    "extraversion": {
        TraitLevel.VERY_HIGH: "highly gregarious, energised by crowds and rarely quiet for long",
        TraitLevel.HIGH: "outgoing and energetic, at ease around other people",
        TraitLevel.MEDIUM: "sociable enough but equally content alone",
        TraitLevel.LOW: "reserved, preferring quieter and low-key settings",
        TraitLevel.VERY_LOW: "markedly withdrawn, avoiding company wherever possible",
    },
    "agreeableness": {
        TraitLevel.VERY_HIGH: "exceptionally warm and accommodating, quick to trust and slow to judge",
        TraitLevel.HIGH: "warm and trusting, inclined to give people the benefit of the doubt",
        TraitLevel.MEDIUM: "considerate but willing to push back when it matters",
        TraitLevel.LOW: "skeptical and direct, weighing claims critically before buying in",
        TraitLevel.VERY_LOW: "highly guarded and blunt, treating most claims as suspect",
    },
    "neuroticism": {
        TraitLevel.VERY_HIGH: "highly strung, easily alarmed and quick to dwell on what might go wrong",
        TraitLevel.HIGH: "sensitive to stress and prone to worry about how things might go wrong",
        TraitLevel.MEDIUM: "subject to the usual ups and downs but mostly even-keeled",
        TraitLevel.LOW: "calm and emotionally steady, rarely rattled",
        TraitLevel.VERY_LOW: "exceptionally unflappable, almost never anxious or upset",
    },
}


# Past tense throughout, so the same clause works after "You" and after a noun.
_EDUCATION_PHRASE: dict[EducationLevel, str] = {
    EducationLevel.BELOW_SECONDARY: "left school before finishing secondary education",
    EducationLevel.SECONDARY: "finished secondary school but didn't go to university",
    EducationLevel.TERTIARY: "completed a university degree",
}


_BAND_OF_QUINTILE = {
    quintile: band
    for band, quintiles in INCOME_BAND_QUINTILES.items()
    for quintile in quintiles
}


def _income_band(quintile: int) -> str:
    """Quintile → relative income band; income is ranked within the person's own country."""
    return f"the {_BAND_OF_QUINTILE[quintile]} income range"


def _dispositions(big_five: BigFive) -> str:
    """The five trait phrases for a persona's sampled levels, in domain order.

    Order comes from `BigFive`'s own field order and is part of the embedded summary,
    so reshuffling it is a re-embedding bill rather than a cosmetic change.
    """
    return "; ".join(
        _TRAIT_PHRASES[trait][bucketize(score)] for trait, score in big_five.traits()
    )


def render_demographics_prompt(persona: Persona) -> str:
    """The demographic half of the vote prompt, on its own.

    Public because the manipulation check needs a trait-free arm, and deriving
    it here rather than re-typing the sentence is what keeps that arm identical
    to the real prompt minus temperament — a reworded copy would ablate wording
    and traits together.
    """
    return (
        f"You are a {persona.age}-year-old {persona.gender} living in "
        f"{COUNTRY_NAME[persona.country]}. You {_EDUCATION_PHRASE[persona.education]}, "
        f"and your income is in {_income_band(persona.income_quintile)} for your country."
    )


def render_persona_prompt(persona: Persona) -> str:
    """Render a persona into its natural-language system prompt.

    Describes the person only — nothing about the options or how to vote; that
    stays in the vote step so position handling lives in one place.
    """
    return (
        f"{render_demographics_prompt(persona)} "
        f"By temperament, you're {_dispositions(persona.big_five)}."
    )


def persona_summary(persona: Persona) -> str:
    """Render a persona as third-person prose, and embed that text so the
    analyst's panelist search can match a description against it.

    Shares the vote prompt's phrasing on purpose: a target description is matched
    against this text, so anything it claims that the prompt does not say would
    promise a panel the panel cannot deliver.
    """
    return (
        f"A {persona.age}-year-old {persona.gender} living in "
        f"{COUNTRY_NAME[persona.country]}, who "
        f"{_EDUCATION_PHRASE[persona.education]}, with an income in "
        f"{_income_band(persona.income_quintile)} for that country. "
        f"By temperament: {_dispositions(persona.big_five)}."
    )


FIXED_PANEL: list[Persona] = [
    Persona(
        id="p1",
        country="US",
        age=34,
        gender="female",
        income_quintile=3,
        education="tertiary",
        big_five=bigfive_from_levels(
            openness=TraitLevel.HIGH,
            conscientiousness=TraitLevel.HIGH,
            extraversion=TraitLevel.MEDIUM,
            agreeableness=TraitLevel.MEDIUM,
            neuroticism=TraitLevel.LOW,
        ),
    ),
    # Traits deliberately cross-cut demographics, so no age or gender implies a
    # personality: a
    # conventional young man, a curious 61-year-old, an anxious/disorganized
    # midlifer, a driven woman with mainstream tastes.
    Persona(
        id="p2",
        country="US",
        age=24,
        gender="male",
        income_quintile=2,
        education="secondary",
        big_five=bigfive_from_levels(
            openness=TraitLevel.VERY_LOW,
            conscientiousness=TraitLevel.HIGH,
            extraversion=TraitLevel.VERY_HIGH,
            agreeableness=TraitLevel.VERY_LOW,
            neuroticism=TraitLevel.MEDIUM,
        ),
    ),
    Persona(
        id="p3",
        country="US",
        age=61,
        gender="female",
        income_quintile=4,
        education="tertiary",
        big_five=bigfive_from_levels(
            openness=TraitLevel.VERY_HIGH,
            conscientiousness=TraitLevel.MEDIUM,
            extraversion=TraitLevel.VERY_LOW,
            agreeableness=TraitLevel.HIGH,
            neuroticism=TraitLevel.LOW,
        ),
    ),
    Persona(
        id="p4",
        country="US",
        age=47,
        gender="male",
        income_quintile=3,
        education="secondary",
        big_five=bigfive_from_levels(
            openness=TraitLevel.MEDIUM,
            conscientiousness=TraitLevel.VERY_LOW,
            extraversion=TraitLevel.MEDIUM,
            agreeableness=TraitLevel.HIGH,
            neuroticism=TraitLevel.VERY_HIGH,
        ),
    ),
    Persona(
        id="p5",
        country="US",
        age=29,
        gender="female",
        income_quintile=4,
        education="tertiary",
        big_five=bigfive_from_levels(
            openness=TraitLevel.MEDIUM,
            conscientiousness=TraitLevel.HIGH,
            extraversion=TraitLevel.MEDIUM,
            agreeableness=TraitLevel.LOW,
            neuroticism=TraitLevel.LOW,
        ),
    ),
]


def voter_summary(persona: Persona) -> VoterSummary:
    """The persona as the report's voter: demographics verbatim, scores as levels.

    The same `bucketize` and the same income band the vote prompt is rendered
    through, so what a reader sees is what the panelist was asked to enact — the
    prompt never mentions a quintile, so neither does the feed.
    """
    return VoterSummary(
        country=persona.country,
        age=persona.age,
        gender=persona.gender,
        education=persona.education,
        income_band=_BAND_OF_QUINTILE[persona.income_quintile],
        traits={trait: bucketize(score) for trait, score in persona.big_five},
    )


def votes_with_voters(
    records: list[VoteRecord], panel: list[Persona]
) -> list[PanelVote]:
    """Join each vote to its voter at assembly time.

    The pipeline still holds the matched personas when the response is built, so
    this is enrichment, not a query. A record's persona is always on the
    panel — the run fingerprinted the question per panelist — so a miss here is
    a bug worth crashing on, not a row to skip.
    """
    personas = {persona.id: persona for persona in panel}
    return [
        PanelVote(
            persona_id=record.persona_id,
            chosen_variant_id=record.chosen_variant_id,
            reason=record.reason,
            voter=voter_summary(personas[record.persona_id]),
        )
        for record in records
    ]
