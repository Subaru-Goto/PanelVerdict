from app.schemas import BigFive, EducationLevel, Locale, Persona, TraitLevel

_TRAIT_PHRASES: dict[str, dict[TraitLevel, str]] = {
    "openness": {
        TraitLevel.HIGH: "curious and imaginative, drawn to new ideas and experiences",
        TraitLevel.MEDIUM: "open to new ideas but still fond of the tried-and-true",
        TraitLevel.LOW: "practical and conventional, preferring the familiar to the novel",
    },
    "conscientiousness": {
        TraitLevel.HIGH: "organized and self-disciplined, careful to think things through",
        TraitLevel.MEDIUM: "reasonably organized without being rigid about it",
        TraitLevel.LOW: "spontaneous and easygoing, not one to fuss over plans or details",
    },
    "extraversion": {
        TraitLevel.HIGH: "outgoing and energetic, at ease around other people",
        TraitLevel.MEDIUM: "sociable enough but equally content with your own company",
        TraitLevel.LOW: "reserved, preferring quieter and low-key settings",
    },
    "agreeableness": {
        TraitLevel.HIGH: "warm and trusting, inclined to give people the benefit of the doubt",
        TraitLevel.MEDIUM: "considerate but willing to push back when it matters",
        TraitLevel.LOW: "skeptical and direct, weighing claims critically before buying in",
    },
    "neuroticism": {
        TraitLevel.HIGH: "sensitive to stress and prone to worry about how things might go wrong",
        TraitLevel.MEDIUM: "subject to the usual ups and downs but mostly even-keeled",
        TraitLevel.LOW: "calm and emotionally steady, rarely rattled",
    },
}


def _join_with_and(items: list[str]) -> str:
    """ "a" / "a and b" / "a, b and c" — a natural inline list."""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


_COUNTRY_NAME: dict[Locale, str] = {
    Locale.US: "the United States",
    Locale.JP: "Japan",
    Locale.DE: "Germany",
}

_EDUCATION_PHRASE: dict[EducationLevel, str] = {
    EducationLevel.LOWER_SECONDARY: "left school before finishing secondary education",
    EducationLevel.UPPER_SECONDARY: "finished secondary school",
    EducationLevel.POST_SECONDARY: "did some post-secondary or vocational study",
    EducationLevel.BACHELOR: "hold a bachelor's degree",
    EducationLevel.MASTER_PLUS: "hold a postgraduate degree",
}


def _income_band(quintile: int) -> str:
    """Quintile → relative income band; income is ranked within the person's own country."""
    if quintile <= 2:
        return "the lower income range"
    if quintile == 3:
        return "the middle income range"
    return "the upper income range"


def render_persona_prompt(persona: Persona) -> str:
    """Render a persona into its natural-language system prompt.

    Describes the person only — nothing about the options or how to vote; that
    stays in the vote step so position handling lives in one place.
    """
    dispositions = "; ".join(
        _TRAIT_PHRASES[trait][level] for trait, level in persona.big_five
    )
    return (
        f"You are a {persona.age}-year-old {persona.gender} living in "
        f"{_COUNTRY_NAME[persona.country]}. You {_EDUCATION_PHRASE[persona.education]}, "
        f"and your income is in {_income_band(persona.income_quintile)} for your country. "
        f"In your spare time you're into {_join_with_and(persona.interests)}. "
        f"By temperament, you're {dispositions}."
    )


FIXED_PANEL: list[Persona] = [
    Persona(
        id="p1",
        country="US",
        age=34,
        gender="female",
        income_quintile=3,
        education="bachelor",
        interests=["trail running", "indie podcasts", "home cooking"],
        big_five=BigFive(
            openness="high",
            conscientiousness="high",
            extraversion="medium",
            agreeableness="medium",
            neuroticism="low",
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
        education="post_secondary",
        interests=["weightlifting", "personal budgeting", "restoring old cars"],
        big_five=BigFive(
            openness="low",
            conscientiousness="high",
            extraversion="high",
            agreeableness="low",
            neuroticism="medium",
        ),
    ),
    Persona(
        id="p3",
        country="US",
        age=61,
        gender="female",
        income_quintile=4,
        education="master_plus",
        interests=["contemporary art", "learning Italian", "birdwatching"],
        big_five=BigFive(
            openness="high",
            conscientiousness="medium",
            extraversion="low",
            agreeableness="high",
            neuroticism="low",
        ),
    ),
    Persona(
        id="p4",
        country="US",
        age=47,
        gender="male",
        income_quintile=3,
        education="upper_secondary",
        interests=["fishing", "classic rock", "grilling"],
        big_five=BigFive(
            openness="medium",
            conscientiousness="low",
            extraversion="medium",
            agreeableness="high",
            neuroticism="high",
        ),
    ),
    Persona(
        id="p5",
        country="US",
        age=29,
        gender="female",
        income_quintile=4,
        education="bachelor",
        interests=["real estate", "home fitness", "true-crime podcasts"],
        big_five=BigFive(
            openness="medium",
            conscientiousness="high",
            extraversion="medium",
            agreeableness="low",
            neuroticism="low",
        ),
    ),
]
