from app.bigfive import _LEVEL_SCORE, bucketize
from app.panel import (
    FIXED_PANEL,
    _EDUCATION_PHRASE,
    _TRAIT_PHRASES,
    _income_band,
    persona_summary,
    render_persona_prompt,
    voter_summary,
    votes_with_voters,
)
from app.schemas import COUNTRY_NAME, BigFive, TraitLevel, VoteRecord
from tests.factories import make_persona

_TRAITS = tuple(BigFive.model_fields)


def _with_traits(**scores: float) -> BigFive:
    base = dict(
        openness=0.0,
        conscientiousness=0.0,
        extraversion=0.0,
        agreeableness=0.0,
        neuroticism=0.0,
    )
    return BigFive(**(base | scores))


def test_every_trait_has_a_phrase_for_every_level() -> None:
    # one table serves both voices, so a missing cell is a KeyError at render for
    # whichever persona happens to draw that intensity
    for trait, phrases in _TRAIT_PHRASES.items():
        assert set(phrases) == set(TraitLevel), trait
    # keyed by BigFive's own field names, so a renamed trait fails here rather
    # than as a KeyError at render for whoever draws that trait first
    assert set(_TRAIT_PHRASES) == set(BigFive.model_fields)


def test_the_traits_are_rendered_in_domain_order() -> None:
    """Order is part of the text the summary was embedded from, so a reshuffle costs a
    re-embedding of the whole pool. Written out rather than looked up: an expected
    value taken from the table the renderer reads is one it cannot disagree with."""
    persona = make_persona().model_copy(
        update={"big_five": _with_traits(openness=-1.0, neuroticism=1.0)}
    )

    assert (
        "practical and conventional, preferring the familiar to the novel; "
        "reasonably organized without being rigid about it" in persona_summary(persona)
    )
    assert persona_summary(persona).endswith(
        "sensitive to stress and prone to worry about how things might go wrong."
    )


def test_the_rendered_income_bands_are_unchanged() -> None:
    """The pool's summaries are already embedded, and re-embedding 5,000 of them
    costs money. Deriving this prose from the shared band mapping must not have
    moved a single word of it."""
    assert [_income_band(quintile) for quintile in range(1, 6)] == [
        "the lower income range",
        "the lower income range",
        "the middle income range",
        "the upper income range",
        "the upper income range",
    ]


def test_no_two_levels_share_a_phrase() -> None:
    # a copy-pasted cell would silently restore the quantization five levels
    # exist to remove — for that one trait only, with every other test green
    phrases = [p for level in _TRAIT_PHRASES.values() for p in level.values()]

    assert len(set(phrases)) == len(phrases)


def test_every_phrase_reaches_a_rendered_summary() -> None:
    # the completeness test checks the table's keys; this checks the phrases
    # actually come out the other end, at every intensity
    persona = make_persona()
    rendered: set[str] = set()
    for level, score in ((lvl, _LEVEL_SCORE[lvl]) for lvl in TraitLevel):
        summary = persona_summary(
            persona.model_copy(
                update={"big_five": _with_traits(**dict.fromkeys(_TRAITS, score))}
            )
        )
        rendered.update(
            phrase
            for phrase in _TRAIT_PHRASES["openness"].values()
            if phrase in summary
        )
        assert _TRAIT_PHRASES["neuroticism"][level] in summary

    assert len(rendered) == len(TraitLevel)


def test_the_fixed_panel_spans_the_full_range_of_intensities() -> None:
    # the hand-authored panel is the demo; if it only ever uses three levels it
    # under-represents the personas the pool actually draws
    levels = {bucketize(score) for p in FIXED_PANEL for _, score in p.big_five}

    assert levels == set(TraitLevel)


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


def test_summary_and_vote_prompt_state_the_same_facts() -> None:
    # what retrieval matches on has to be what the persona is told it is,
    # otherwise a retrieved panel isn't the panel that votes. The two renderers
    # share only the clause fragments, so every shared fact needs asserting —
    # traits alone would let education or income drift between the voices.
    persona = make_persona()

    summary = persona_summary(persona)
    prompt = render_persona_prompt(persona)

    for fact in (
        "34-year-old female",
        COUNTRY_NAME[persona.country],
        _EDUCATION_PHRASE[persona.education],
        _income_band(persona.income_quintile),
        _TRAIT_PHRASES["agreeableness"][TraitLevel.MEDIUM],
    ):
        assert fact in summary
        assert fact in prompt


def test_no_trait_score_reaches_either_rendering() -> None:
    """Traits are described in sentences, never as numbers or scale points: BFI-2-E
    style descriptions of the sampled level are what enacts a trait most like a human
    (Huang, Zhang, Soto & Evans 2026), and a persona handed "openness: 1.75" is being
    asked to reason about a questionnaire item about itself instead. Age is the only
    number that belongs in either voice, so the digits are pinned exactly — a score
    leaking in through a reworded template shows up as a digit that is not the age."""
    persona = make_persona().model_copy(
        update={"big_five": _with_traits(openness=1.75, neuroticism=-2.25)}
    )

    for rendering in (render_persona_prompt(persona), persona_summary(persona)):
        assert "".join(c for c in rendering if c.isdigit()) == "34"


def test_a_stronger_trait_score_reads_differently() -> None:
    # the whole point of five levels: at three, 0.6 and 2.0 rendered identically,
    # so cosine could not tell these two personas apart
    mild = make_persona().model_copy(update={"big_five": _with_traits(openness=0.6)})
    intense = make_persona().model_copy(update={"big_five": _with_traits(openness=2.0)})

    assert persona_summary(mild) != persona_summary(intense)
    assert _TRAIT_PHRASES["openness"][TraitLevel.HIGH] in persona_summary(mild)
    assert _TRAIT_PHRASES["openness"][TraitLevel.VERY_HIGH] in persona_summary(intense)


class TestVoterSummary:
    """The voter as the report shows them: demographics verbatim, traits as the
    rendered levels — the same bucketize the vote prompt already speaks."""

    def test_it_carries_the_demographics_verbatim(self) -> None:
        persona = make_persona(
            "DE-00007",
            country="DE",
            age=61,
            gender="male",
            income_quintile=2,
            education="secondary",
        )

        summary = voter_summary(persona)

        assert summary.country == persona.country
        assert summary.age == 61
        assert summary.gender == "male"
        # Quintile 2 renders as the lower band — the word the vote prompt used,
        # which is why the summary never carries the quintile itself.
        assert summary.income_band == "lower"
        assert summary.education == persona.education

    def test_it_renders_every_trait_at_its_bucketized_level(self) -> None:
        """Levels from the bucketize spec, not recomputed: -1.6 is past the outer
        cutoff, -1.0 past the inner, 0.0 the middle, 1.0 and 2.0 the mirrors."""
        persona = make_persona().model_copy(
            update={
                "big_five": BigFive(
                    openness=-1.6,
                    conscientiousness=-1.0,
                    extraversion=0.0,
                    agreeableness=1.0,
                    neuroticism=2.0,
                )
            }
        )

        summary = voter_summary(persona)

        assert summary.traits == {
            "openness": TraitLevel.VERY_LOW,
            "conscientiousness": TraitLevel.LOW,
            "extraversion": TraitLevel.MEDIUM,
            "agreeableness": TraitLevel.HIGH,
            "neuroticism": TraitLevel.VERY_HIGH,
        }


class TestVotesWithVoters:
    def test_each_vote_is_joined_to_its_own_voter(self) -> None:
        """The pairing is the point: a feed that attached the right fields to the
        wrong panelist would still render beautifully."""
        young = make_persona("US-00001", age=22)
        old = make_persona("US-00002", age=83)
        records = [
            VoteRecord(
                persona_id="US-00002",
                test_id="t",
                chosen_variant_id="b",
                presentation_order=["a", "b"],
                reason="second reads clearer",
            ),
            VoteRecord(
                persona_id="US-00001",
                test_id="t",
                chosen_variant_id="a",
                presentation_order=["a", "b"],
                reason="the discount is concrete",
            ),
        ]

        votes = votes_with_voters(records, [young, old])

        assert [vote.persona_id for vote in votes] == ["US-00002", "US-00001"]
        assert [vote.voter.age for vote in votes] == [83, 22]
        assert votes[0].chosen_variant_id == "b"
        assert votes[0].reason == "second reads clearer"
