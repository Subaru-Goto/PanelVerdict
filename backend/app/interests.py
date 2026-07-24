import re
from typing import Protocol

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
_MAX_TAG_LEN = 40

# Short noun-phrase tags: alphanumerics plus internal spaces/hyphens/apostrophes,
# starting and ending on an alphanumeric. Excluding punctuation and URLs.
# Digits stay: "3D printing", "K-pop", "Formula 1" are real hobbies.
_TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '\-]*[A-Za-z0-9]$")

_EDUCATION_DESC: dict[EducationLevel, str] = {
    EducationLevel.BELOW_SECONDARY: "did not finish secondary school",
    EducationLevel.SECONDARY: "finished secondary school, no university degree",
    EducationLevel.TERTIARY: "has a university degree",
}


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


def build_interest_prompt(demographics: PersonaDemographics, big_five: BigFive) -> str:
    """The generation instruction: describe the person, then ask for interests."""
    return (
        "Invent a realistic set of personal interests for one specific individual.\n"
        f"Person: {demographics.age}-year-old {demographics.gender} in "
        f"{COUNTRY_NAME[demographics.country]}; "
        f"{_EDUCATION_DESC[demographics.education]}; "
        f"{_income_desc(demographics.income_quintile)}.\n"
        f"Personality (Big Five levels): {_trait_levels(big_five)}.\n"
        f"Give {MIN_INTERESTS}-{MAX_INTERESTS} specific hobbies or interests as short "
        "noun phrases (e.g. 'trail running', 'restoring old cars', 'playing football'), never broad "
        "categories like 'sports'. Write a distinctive individual, not the "
        "stereotype of their demographic — at least one interest may cut against "
        "the obvious profile. Let personality and life stage shape the choices; "
        "unusual-but-plausible interests are welcome when the personality supports "
        "them."
    )


def _clean_tags(raw: list[str]) -> list[str]:
    """Trim, collapse internal whitespace, drop blanks, dedupe case-insensitively."""
    seen: set[str] = set()
    out: list[str] = []
    for tag in raw:
        cleaned = " ".join(tag.split())
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
    max_attempts: int = 3,
) -> list[str]:
    """Generate one persona's interests, regenerating until they pass the gate."""
    prompt = build_interest_prompt(demographics, big_five)
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
