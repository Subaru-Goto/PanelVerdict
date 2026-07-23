"""Stage 3 — synthesize the one un-groundable persona field: interests.

Demographics (006b) and Big Five (006c) are sampled numerically; interests are
LLM-synthesized conditioned on both, then embedded *per interest* for fuzzy
targeting and the 006e anti-stereotype audit. Design: issues/006d-interests-synthesis.md.

The LLM and embedder are injected as Protocols so this module is import-safe and
unit-testable without the network; the concrete OpenRouter adapters live in
app.llm. Generation is single-persona (D5): each persona is an independent draw,
which is what makes the 006e population audit's frequencies unbiased.
"""

import re
from typing import Protocol

from app.bigfive import bucketize
from app.schemas import (
    COUNTRY_NAME,
    BigFive,
    EducationLevel,
    InterestSynthesis,
    Persona,
    PersonaDemographics,
)

MIN_INTERESTS = 3
MAX_INTERESTS = 5
_MIN_TAG_LEN = 3
_MAX_TAG_LEN = 40

# Short noun-phrase tags only: a letter, then letters/spaces/hyphens/apostrophes,
# ending on a letter. Combined with the length cap this bounds the injection
# surface (no digits, punctuation, or URLs) without being the full screen — that,
# plus the statistical audit, is 006e.
_TAG_PATTERN = re.compile(r"^[A-Za-z][A-Za-z '\-]*[A-Za-z]$")

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
    """The generation instruction: describe the person, then ask for interests.

    Third-person and generation-facing — deliberately distinct from the
    second-person vote prompt in app.panel. Encodes D2 (anti-stereotype) and
    D3 (specific, not categorical).
    """
    return (
        "Invent a realistic set of personal interests for one specific individual.\n"
        f"Person: {demographics.age}-year-old {demographics.gender} in "
        f"{COUNTRY_NAME[demographics.country]}; "
        f"{_EDUCATION_DESC[demographics.education]}; "
        f"{_income_desc(demographics.income_quintile)}.\n"
        f"Personality (Big Five levels): {_trait_levels(big_five)}.\n"
        f"Give {MIN_INTERESTS}-{MAX_INTERESTS} specific hobbies or interests as short "
        "noun phrases (e.g. 'trail running', 'restoring old cars'), never broad "
        "categories like 'sports'. Write a distinctive individual, not the "
        "stereotype of their demographic — at least one interest may cut against "
        "the obvious profile. Let personality and life stage shape the choices; "
        "unusual-but-plausible interests are welcome when the personality supports "
        "them."
    )


def _normalize(raw: list[str]) -> list[str]:
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
    """Generate one persona's interests, regenerating until they pass the gate.

    Non-deterministic by nature (the LLM field) — 006f freezes the result by
    persistence. Raises InvalidInterests if no attempt validates.
    """
    prompt = build_interest_prompt(demographics, big_five)
    last_error: InvalidInterests | None = None
    for _ in range(max_attempts):
        tags = _normalize(llm.generate(prompt=prompt).interests)
        try:
            _validate(tags)
            return tags
        except InvalidInterests as error:
            last_error = error
    raise InvalidInterests(
        f"no valid interest set in {max_attempts} attempts (last: {last_error})"
    )


def embed_interests(tags: list[str], *, embedder: Embedder) -> list[list[float]]:
    """One vector per interest (D4).

    Each hobby is embedded separately, not as a joined string, so 006e can
    cluster individual interests; persona-level targeting mean-pools these.
    """
    return embedder.embed(tags)


def build_persona(
    *,
    persona_id: str,
    demographics: PersonaDemographics,
    big_five: BigFive,
    interests: list[str],
) -> Persona:
    """Assemble the sampled parts into a full Persona."""
    return Persona(
        id=persona_id,
        **demographics.model_dump(),
        interests=interests,
        big_five=big_five,
    )
