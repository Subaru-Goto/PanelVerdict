import re
from collections.abc import Sequence
from typing import Protocol

import numpy as np

from app.bigfive import bucketize
from app.content_checks import UnsafeInterest, screen_interests
from app.schemas import (
    COUNTRY_NAME,
    BigFive,
    EducationLevel,
    InterestSynthesis,
    PersonaDemographics,
)

MIN_INTERESTS = 3
MAX_INTERESTS = 5
_MIN_TAG_LEN = 3
_MAX_TAG_LEN = 60

# Short noun-phrase tags: Unicode letters/digits plus internal spaces, hyphens,
# and apostrophes, starting and ending on a letter or digit. Excludes punctuation
# and URLs. Unicode (not [A-Za-z]) so English loanwords keep their diacritics
# ("Pokémon", "café"); digits stay for "3D printing", "Formula 1". [^\W_] is a
# word character minus underscore — i.e. any Unicode letter or digit.
_TAG_PATTERN = re.compile(r"^[^\W_](?:[^\W_]|[ '\-])*[^\W_]$")

# LLMs emit typographic punctuation (curly quotes, en/em/non-breaking hyphens):
# cosmetically identical to ASCII but distinct code points the pattern rejects.
# Fold them to ASCII before validation so they pass and dedupe as one spelling.
_PUNCTUATION_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
    }
)

_EDUCATION_DESC: dict[EducationLevel, str] = {
    EducationLevel.BELOW_SECONDARY: "did not finish secondary school",
    EducationLevel.SECONDARY: "finished secondary school, no university degree",
    EducationLevel.TERTIARY: "has a university degree",
}


# Example bank for the generation prompt. Static examples anchored the whole
# pool onto themselves ("restoring old cars" -> a restoration monoculture), so
# each persona gets its own draw instead — the anchoring effect then *injects*
# variety, which matters because the interest model rejects a temperature knob.
# Two tiers so every prompt is anchored mostly on mainstream hobbies: the first
# pool run had zero of these, skewing the panel far from the median consumer.
_COMMON_EXAMPLES: tuple[str, ...] = (
    "watching football",
    "video games",
    "cooking",
    "baking",
    "reading novels",
    "jogging",
    "going to the gym",
    "hiking",
    "fishing",
    "gardening",
    "watching movies",
    "playing guitar",
    "cycling",
    "swimming",
    "yoga",
    "board games",
    "karaoke",
    "watching anime",
    "basketball",
    "camping",
    "knitting",
    "home improvement",
    "walking the dog",
    "podcasts",
    "crossword puzzles",
    "thrift shopping",
    "dancing",
    "baseball",
    "tennis",
    "golf",
    "bowling",
    "birdwatching",
    "sewing",
    "drawing",
    "playing cards",
    "watching TV dramas",
    "barbecue",
    "visiting museums",
    "live concerts",
    "running",
    "table tennis",
    "badminton",
    "photography",
    "travel",
    "chess",
    "volleyball",
    "skiing",
    "picnics in the park",
)
_UNCOMMON_EXAMPLES: tuple[str, ...] = (
    "beekeeping",
    "lockpicking",
    "amateur radio",
    "fencing",
    "pottery",
    "stand-up comedy",
    "rock climbing",
    "archery",
    "salsa dancing",
    "calligraphy",
    "bonsai",
    "homebrewing",
    "woodworking",
    "amateur astronomy",
    "drone racing",
    "escape rooms",
    "cosplay",
    "geocaching",
    "mushroom foraging",
    "blacksmithing",
    "triathlon",
    "quilting",
    "model trains",
    "zine making",
)
_N_COMMON_EXAMPLES = 3
_N_UNCOMMON_EXAMPLES = 1


def sample_prompt_examples(rng: np.random.Generator) -> list[str]:
    """One persona's prompt examples: mostly mainstream plus one distinctive."""
    picks = [
        _COMMON_EXAMPLES[i]
        for i in rng.choice(len(_COMMON_EXAMPLES), size=_N_COMMON_EXAMPLES, replace=False)
    ] + [
        _UNCOMMON_EXAMPLES[i]
        for i in rng.choice(
            len(_UNCOMMON_EXAMPLES), size=_N_UNCOMMON_EXAMPLES, replace=False
        )
    ]
    # shuffle so the distinctive example isn't always in the same position —
    # a fixed slot would teach the model "always end with the quirky one"
    return [picks[i] for i in rng.permutation(len(picks))]


class InvalidInterests(ValueError):
    """A synthesized interest set that failed the generation-time gate."""


class InterestLLM(Protocol):
    def generate(self, *, prompt: str) -> InterestSynthesis: ...


class Embedder(Protocol):
    """Embeds each text into its own vector."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _income_desc(quintile: int) -> str:
    if quintile <= 2:
        return "lower income for their country"
    if quintile == 3:
        return "middle income for their country"
    return "upper income for their country"


def _trait_levels(big_five: BigFive) -> str:
    """ "openness high, conscientiousness low, …" — the sampled levels in words."""
    return ", ".join(f"{trait} {bucketize(score).value}" for trait, score in big_five)


def build_interest_prompt(
    demographics: PersonaDemographics,
    big_five: BigFive,
    examples: Sequence[str],
) -> str:
    """The generation instruction: describe the person, then ask for interests.

    `examples` are per-persona (see `sample_prompt_examples`): a static list
    anchored every persona onto the same few hobbies.
    """
    rendered_examples = ", ".join(f"'{example}'" for example in examples)
    return (
        "Invent a realistic set of personal interests for one specific individual.\n"
        f"Person: {demographics.age}-year-old {demographics.gender} in "
        f"{COUNTRY_NAME[demographics.country]}; "
        f"{_EDUCATION_DESC[demographics.education]}; "
        f"{_income_desc(demographics.income_quintile)}.\n"
        f"Personality (Big Five levels): {_trait_levels(big_five)}.\n"
        f"Give {MIN_INTERESTS}-{MAX_INTERESTS} interests. Rules:\n"
        "- Each is a real, recognized hobby or activity a person would name if "
        f"asked 'what are you into?' — e.g. {rendered_examples}.\n"
        "- 1-4 words each; neither a broad category ('sports') nor an invented "
        "micro-niche.\n"
        "- In English, plain ASCII punctuation, no numbering or explanations.\n"
        "- The interests must differ from each other in kind.\n"
        "Make the person distinctive through an unexpected MIX of ordinary "
        "interests, not the stereotype of their demographic — at least one "
        "interest may cut against the obvious profile. Let personality and life "
        "stage shape the choices."
    )


def _clean_tags(raw: list[str]) -> list[str]:
    """Fold typographic punctuation to ASCII, trim, collapse internal whitespace,
    drop blanks, dedupe case-insensitively."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in raw:
        cleaned = " ".join(tag.translate(_PUNCTUATION_FOLD).split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def _validate(tags: list[str]) -> None:
    """Enforce the generation-time gate; raise InvalidInterests on any breach."""
    if not MIN_INTERESTS <= len(tags) <= MAX_INTERESTS:
        raise InvalidInterests(
            f"need {MIN_INTERESTS}-{MAX_INTERESTS} interests, got {len(tags)}"
        )
    for tag in tags:
        if not _MIN_TAG_LEN <= len(tag) <= _MAX_TAG_LEN:
            raise InvalidInterests(f"interest {tag!r} length out of range")
        if not _TAG_PATTERN.match(tag):
            raise InvalidInterests(f"interest {tag!r} has invalid characters")


def synthesize_interests(
    demographics: PersonaDemographics,
    big_five: BigFive,
    *,
    llm: InterestLLM,
    examples: Sequence[str],
    max_attempts: int = 3,
) -> list[str]:
    """Generate one persona's interests, regenerating until they pass the gate."""
    prompt = build_interest_prompt(demographics, big_five, examples)
    last_error: InvalidInterests | UnsafeInterest | None = None
    for _ in range(max_attempts):
        tags = _clean_tags(llm.generate(prompt=prompt).interests)
        try:
            _validate(tags)
            screen_interests(tags)
            return tags
        except (InvalidInterests, UnsafeInterest) as error:
            last_error = error
    raise InvalidInterests(
        f"no valid interest set in {max_attempts} attempts (last: {last_error})"
    )


def embed_interests(tags: list[str], *, embedder: Embedder) -> list[list[float]]:
    """One vector per interest in embedded format."""
    return embedder.embed(tags)
