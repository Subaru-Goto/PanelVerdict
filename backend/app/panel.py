from app.schemas import BigFive, Persona, TraitLevel

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
        f"{persona.region}, with {persona.income} income and {persona.education}. "
        f"In your spare time you're into {_join_with_and(persona.interests)}. "
        f"By temperament, you're {dispositions}."
    )


FIXED_PANEL: list[Persona] = [
    Persona(
        id="p1",
        age=34,
        gender="female",
        region="Pacific Northwest, US",
        income="middle",
        education="bachelor's degree",
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
        age=24,
        gender="male",
        region="Midwest, US",
        income="low",
        education="some college",
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
        age=61,
        gender="female",
        region="Northeast, US",
        income="high",
        education="graduate degree",
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
        age=47,
        gender="male",
        region="South, US",
        income="middle",
        education="high school",
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
        age=29,
        gender="female",
        region="Southwest, US",
        income="high",
        education="bachelor's degree",
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
