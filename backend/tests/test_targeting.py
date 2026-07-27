from typing import get_args

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.llm import build_target_messages
from app.schemas import (
    INCOME_BAND_QUINTILES,
    MAX_PERSONA_AGE,
    MIN_PERSONA_AGE,
    BigFive,
    CultureTag,
    EducationLevel,
    IncomeBand,
    Locale,
    TargetRequest,
    TraitLevel,
    TraitName,
)


def test_trait_name_matches_the_big_five_fields() -> None:
    """The translator names a trait; the renderer looks that name up in the phrase
    table keyed by BigFive's fields. A Literal that drifts from those fields would
    typecheck and then KeyError on a real target."""
    assert get_args(TraitName) == tuple(BigFive.model_fields)


def test_income_bands_partition_the_quintiles() -> None:
    assert sorted(q for qs in INCOME_BAND_QUINTILES.values() for q in qs) == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert tuple(INCOME_BAND_QUINTILES) == get_args(IncomeBand)


def test_the_prompt_names_every_value_the_pool_can_express() -> None:
    """The vocabulary is derived from the enums rather than typed out, so a country
    or trait level added to the schema reaches the prompt without an edit here.

    A value missing from the prompt is the expensive failure: the model cannot emit
    what it was never told exists, so that slice of the pool becomes unreachable by
    any target description — silently, since nothing raises.
    """
    prompt = build_target_messages("anyone")[0].content
    assert isinstance(prompt, str)

    vocabulary = (
        [locale.value for locale in Locale]
        + [tag.value for tag in CultureTag]
        + [level.value for level in EducationLevel]
        + [level.value for level in TraitLevel]
        + list(get_args(TraitName))
        + list(get_args(IncomeBand))
        + [str(MIN_PERSONA_AGE), str(MAX_PERSONA_AGE)]
    )
    missing = [term for term in vocabulary if term not in prompt]
    assert missing == []


def test_the_description_is_the_human_message_verbatim() -> None:
    """Untrusted text stays in the human turn, away from the instructions."""
    messages = build_target_messages("cautious homeowners in their 40s")

    assert len(messages) == 2
    system, human = messages
    assert isinstance(system, SystemMessage)
    assert isinstance(human, HumanMessage)
    assert human.content == "cautious homeowners in their 40s"


def test_a_target_request_defaults_to_asking_for_nothing() -> None:
    """An empty request is the honest reading of "anyone", and every field has to be
    optional for the model to be able to say "these words mapped to nothing"."""
    request = TargetRequest()

    assert request.regions == []
    assert request.traits == []
    assert request.unmapped == []
    assert request.min_age is None
    assert request.gender is None


def test_an_inverted_age_range_is_rejected() -> None:
    """A range with no members would return an empty panel that looks like a
    coverage gap. Failing the translation says which of the two it was."""
    with pytest.raises(ValidationError):
        TargetRequest(min_age=50, max_age=30)


def test_an_age_range_of_one_year_is_allowed() -> None:
    assert TargetRequest(min_age=40, max_age=40).max_age == 40
