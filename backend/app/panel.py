from collections.abc import Mapping

from app.bigfive import bigfive_from_levels, bucketize
from app.schemas import (
    BigFive,
    COUNTRY_NAME,
    EducationLevel,
    INCOME_BAND_QUINTILES,
    Persona,
    TraitLevel,
    TraitName,
)

# Five intensities per trait, phrased without pronouns so the vote prompt (second
# person) and the summary embedded for retrieval (third person) can share one
# table — the persona a query matches has to be the persona that votes. Wording
# is BFI-2-Expanded-style descriptions of the sampled level, never numbers (006).
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


def render_trait_phrases(levels: Mapping[TraitName, TraitLevel]) -> str:
    """The phrases for the named trait levels, in domain order.

    Public because a target description is matched against the embedded persona
    summary, so the query has to be written in the summary's own words. Rendering it
    through this table rather than a paraphrase is what makes the similarity mean
    something; anything else compares two vocabularies.

    Takes a partial mapping: a target usually names one or two traits, and a query
    should not invent levels for the rest.
    """
    return "; ".join(
        _TRAIT_PHRASES[trait][levels[trait]]
        for trait in _TRAIT_PHRASES
        if trait in levels
    )


def _dispositions(big_five: BigFive) -> str:
    """The five trait phrases for a persona's sampled levels, in domain order."""
    return render_trait_phrases({trait: bucketize(score) for trait, score in big_five})


def render_demographics_prompt(persona: Persona) -> str:
    """The demographic half of the vote prompt, on its own.

    Public because 014's manipulation check needs a trait-free arm, and deriving
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
    """Render a persona as third-person prose, for the embedding 007 retrieves on.

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
    # Traits deliberately cross-cut demographics (001 anti-stereotype): a
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
