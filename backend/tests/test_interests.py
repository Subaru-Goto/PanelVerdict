import pytest

from app.bigfive import bigfive_from_levels
from app.interests import (
    MAX_INTERESTS,
    InvalidInterests,
    _normalize,
    _validate,
    build_interest_prompt,
    build_persona,
    embed_interests,
    synthesize_interests,
)
from app.schemas import BigFive, InterestSynthesis, PersonaDemographics, TraitLevel


class StubInterestLLM:
    """InterestLLM double: returns each canned batch in turn, then repeats the
    last one — so a single invalid batch models "always invalid"."""

    def __init__(self, *batches: list[str]) -> None:
        self._batches = list(batches)
        self.calls = 0

    def generate(self, *, prompt: str) -> InterestSynthesis:
        batch = self._batches[min(self.calls, len(self._batches) - 1)]
        self.calls += 1
        return InterestSynthesis(interests=list(batch))


class StubEmbedder:
    """Embedder double: records exactly what it was asked to embed."""

    def __init__(self, dim: int = 4) -> None:
        self._dim = dim
        self.seen: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.seen.append(list(texts))
        return [[float(i)] * self._dim for i in range(len(texts))]


def _demographics(**overrides: object) -> PersonaDemographics:
    base: dict[str, object] = {
        "country": "US",
        "age": 34,
        "gender": "female",
        "income_quintile": 3,
        "education": "tertiary",
    }
    base.update(overrides)
    return PersonaDemographics(**base)


def _big_five() -> BigFive:
    return bigfive_from_levels(
        openness=TraitLevel.HIGH,
        conscientiousness=TraitLevel.HIGH,
        extraversion=TraitLevel.MEDIUM,
        agreeableness=TraitLevel.MEDIUM,
        neuroticism=TraitLevel.LOW,
    )


_VALID = ["trail running", "home cooking", "indie podcasts"]


def test_build_interest_prompt_conditions_on_demographics_and_traits() -> None:
    prompt = build_interest_prompt(_demographics(), _big_five())

    assert "34-year-old female" in prompt
    assert "the United States" in prompt
    assert "university degree" in prompt
    # every sampled trait level is spelled out for the model
    assert "openness high" in prompt
    assert "neuroticism low" in prompt
    # the anti-stereotype instruction (D2) and specific-not-categorical ask (D3)
    assert "not the" in prompt and "stereotype" in prompt
    assert f"{MAX_INTERESTS}" in prompt


def test_normalize_trims_collapses_and_dedupes_case_insensitively() -> None:
    assert _normalize(["  trail   running ", "Trail Running", "", "cooking"]) == [
        "trail running",
        "cooking",
    ]


@pytest.mark.parametrize(
    "tags",
    [
        ["reading", "cooking"],  # too few
        ["a", "b", "c", "d", "e", "f"],  # too many
        ["trail running", "home cooking", "x"],  # a tag shorter than the min
        ["trail running", "home cooking", "a" * 41],  # a tag past the max length
        ["trail running", "home cooking", "drop table; hack"],  # bad characters
        ["trail running", "home cooking", "web 2 dev"],  # digits not allowed
    ],
)
def test_validate_rejects_bad_sets(tags: list[str]) -> None:
    with pytest.raises(InvalidInterests):
        _validate(tags)


def test_validate_accepts_a_good_set() -> None:
    _validate(["trail running", "restoring old cars", "women's football"])


def test_synthesize_returns_normalized_tags_on_first_valid_batch() -> None:
    llm = StubInterestLLM(["  trail running ", "home cooking", "indie podcasts"])
    result = synthesize_interests(_demographics(), _big_five(), llm=llm)

    assert result == _VALID  # normalized: trimmed, case preserved
    assert llm.calls == 1


def test_synthesize_regenerates_until_valid() -> None:
    llm = StubInterestLLM(["too", "few"], _VALID)  # first batch invalid, then valid
    result = synthesize_interests(_demographics(), _big_five(), llm=llm)

    assert result == _VALID
    assert llm.calls == 2


def test_synthesize_raises_after_max_attempts() -> None:
    llm = StubInterestLLM(["too", "few"])  # always invalid
    with pytest.raises(InvalidInterests):
        synthesize_interests(_demographics(), _big_five(), llm=llm, max_attempts=2)
    assert llm.calls == 2


def test_embed_interests_is_one_vector_per_interest() -> None:
    embedder = StubEmbedder()
    vectors = embed_interests(_VALID, embedder=embedder)

    assert len(vectors) == len(_VALID)
    # each interest was embedded separately (not joined into one string)
    assert embedder.seen == [_VALID]


def test_build_persona_assembles_the_sampled_parts() -> None:
    big_five = _big_five()
    persona = build_persona(
        persona_id="p1",
        demographics=_demographics(),
        big_five=big_five,
        interests=_VALID,
    )

    assert persona.id == "p1"
    assert persona.age == 34
    assert persona.country.value == "US"
    assert persona.interests == _VALID
    assert persona.big_five == big_five
