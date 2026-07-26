import pytest

from app.panel import (
    _TRAIT_PHRASES,
    _join_with_and,
    persona_summary,
    render_persona_prompt,
)
from app.schemas import BigFive, TraitLevel
from tests.factories import make_persona


def _with_traits(**scores: float) -> BigFive:
    base = dict(
        openness=0.0,
        conscientiousness=0.0,
        extraversion=0.0,
        agreeableness=0.0,
        neuroticism=0.0,
    )
    return BigFive(**(base | scores))


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        (["solo"], "solo"),
        (["a", "b"], "a and b"),
        (["a", "b", "c"], "a, b and c"),
        (["a", "b", "c", "d"], "a, b, c and d"),
    ],
)
def test_join_with_and(items: list[str], expected: str) -> None:
    assert _join_with_and(items) == expected


def test_join_with_and_empty_raises() -> None:
    with pytest.raises(IndexError):
        _join_with_and([])


def test_every_trait_has_a_phrase_for_every_level() -> None:
    # one table serves both voices, so a missing cell is a KeyError at render for
    # whichever persona happens to draw that intensity
    for trait, phrases in _TRAIT_PHRASES.items():
        assert set(phrases) == set(TraitLevel), trait
    # keyed by BigFive's own field names, so a renamed trait fails here rather
    # than as a KeyError at render for whoever draws that trait first
    assert set(_TRAIT_PHRASES) == set(BigFive.model_fields)


def test_phrases_carry_no_pronoun_so_both_voices_can_share_them() -> None:
    # the frame sentence owns the grammatical person; a phrase containing "you"
    # or "their" would read wrong in one of the two renderings
    for phrases in _TRAIT_PHRASES.values():
        for phrase in phrases.values():
            words = phrase.replace(",", " ").split()
            assert not {"you", "your", "they", "their", "he", "she"} & set(words)


def test_vote_prompt_addresses_the_persona_directly() -> None:
    prompt = render_persona_prompt(make_persona())

    assert prompt.startswith("You are a 34-year-old female")
    assert "your country" in prompt


def test_summary_describes_the_persona_in_the_third_person() -> None:
    summary = persona_summary(make_persona())

    assert "34-year-old female" in summary
    assert "the United States" in summary
    assert "university degree" in summary
    assert "middle income range" in summary
    for pronoun in (" you ", " your ", "You "):
        assert pronoun not in summary


def test_summary_and_vote_prompt_describe_the_same_temperament() -> None:
    # what retrieval matches on has to be what the persona is told it is,
    # otherwise a retrieved panel isn't the panel that votes
    persona = make_persona()

    phrase = _TRAIT_PHRASES["agreeableness"][TraitLevel.MEDIUM]

    assert phrase in persona_summary(persona)
    assert phrase in render_persona_prompt(persona)


def test_a_stronger_trait_score_reads_differently() -> None:
    # the whole point of five levels: at three, 0.6 and 2.0 rendered identically,
    # so cosine could not tell these two personas apart
    mild = make_persona().model_copy(update={"big_five": _with_traits(openness=0.6)})
    intense = make_persona().model_copy(update={"big_five": _with_traits(openness=2.0)})

    assert persona_summary(mild) != persona_summary(intense)
    assert _TRAIT_PHRASES["openness"][TraitLevel.HIGH] in persona_summary(mild)
    assert _TRAIT_PHRASES["openness"][TraitLevel.VERY_HIGH] in persona_summary(intense)
