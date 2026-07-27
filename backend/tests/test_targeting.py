from typing import get_args

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from factories import DIM, make_assembled, make_persona

from app.llm import build_target_messages
from app.persistence import persist_pool
from app.targeting import resolve_target, select_panel
from app.schemas import (
    COUNTRY_NAME,
    INCOME_BAND_QUINTILES,
    MAX_PERSONA_AGE,
    MIN_PERSONA_AGE,
    BigFive,
    CultureTag,
    EducationLevel,
    IncomeBand,
    Locale,
    RequestedRegion,
    TargetQuery,
    TargetRequest,
    TraitLevel,
    TraitName,
    TraitRequest,
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


# The high-neuroticism phrase, written out rather than looked up: an expected value
# taken from the renderer is one the renderer cannot disagree with. It is also the
# text the pool's summaries were embedded from, so a change here is a re-embedding
# bill and should be loud.
_HIGH_NEUROTICISM = (
    "sensitive to stress and prone to worry about how things might go wrong"
)


def _warnings(query: TargetQuery) -> list[str]:
    return [n.message for n in query.notices if n.severity == "warning"]


def _readings(query: TargetQuery) -> list[str]:
    return [n.message for n in query.notices if n.severity == "reading"]


def test_a_seeded_country_resolves_with_no_warning() -> None:
    query = resolve_target(
        TargetRequest(regions=[RequestedRegion(label="Japan", country_code="JP")])
    )

    assert query.countries == (Locale.JP,)
    assert _warnings(query) == []


def test_a_lowercase_country_code_still_resolves() -> None:
    query = resolve_target(
        TargetRequest(regions=[RequestedRegion(label="Germany", country_code="de")])
    )

    assert query.countries == (Locale.DE,)


def test_an_unseeded_country_falls_back_to_its_culture_tag_and_says_so() -> None:
    """Japan is a weak proxy for China, so the substitution has to reach the
    customer or the panel reads as China's."""
    query = resolve_target(
        TargetRequest(
            regions=[
                RequestedRegion(
                    label="China", country_code="CN", culture_tag=CultureTag.ASIAN
                )
            ]
        )
    )

    assert query.countries == (Locale.JP,)
    (warning,) = _warnings(query)
    assert "China" in warning
    assert "Japan" in warning


def test_a_multi_country_label_falls_back_on_its_tag_alone() -> None:
    """ "Europe" names no single country, so the country rung cannot apply — but the
    coarse rung still can, and that is the ladder's whole point."""
    query = resolve_target(
        TargetRequest(
            regions=[RequestedRegion(label="Europe", culture_tag=CultureTag.WESTERN)]
        )
    )

    assert query.countries == (Locale.US, Locale.DE)
    assert len(_warnings(query)) == 1


def test_a_region_off_the_ladder_falls_back_to_the_whole_pool() -> None:
    """Signed off 2026-07-27: a dead end helps nobody, so an unservable region is
    answered with every country we have — loudly, and marked as unmatched."""
    query = resolve_target(
        TargetRequest(regions=[RequestedRegion(label="Nigeria", country_code="NG")])
    )

    assert set(query.countries) == set(Locale)
    assert query.coverage == "unmatched"
    assert "Nigeria" in _warnings(query)[0]


def test_the_whole_pool_fallback_says_it_is_not_the_audience_asked_for() -> None:
    """The panel is now non-empty and geographically wrong, which is a worse thing to
    report quietly than an empty one. The warning has to name both what was searched
    and what the result does not mean."""
    query = resolve_target(
        TargetRequest(regions=[RequestedRegion(label="Nigeria", country_code="NG")])
    )

    fallback = " ".join(_warnings(query))
    for country in COUNTRY_NAME.values():
        assert country in fallback
    assert "not matched" in fallback


def test_a_partly_served_target_is_not_diluted_by_the_fallback() -> None:
    """The fallback is a last resort for the whole query, not a per-region one. Adding
    Japan and Germany because Nigeria failed would take US personas out of a panel
    that could have been entirely American."""
    query = resolve_target(
        TargetRequest(
            regions=[
                RequestedRegion(label="the US", country_code="US"),
                RequestedRegion(label="Nigeria", country_code="NG"),
            ]
        )
    )

    assert query.countries == (Locale.US,)
    assert query.coverage == "requested"


def test_naming_no_country_is_not_the_same_as_failing_to_serve_one() -> None:
    """Both draw the whole pool, so the panel alone cannot tell them apart — one is
    exactly what was asked for, the other is a substitution. `coverage` is the only
    thing that distinguishes them, which is why it exists."""
    asked_for_nothing = resolve_target(TargetRequest())
    could_not_serve = resolve_target(
        TargetRequest(regions=[RequestedRegion(label="Nigeria", country_code="NG")])
    )

    assert asked_for_nothing.countries == could_not_serve.countries
    assert asked_for_nothing.coverage == "requested"
    assert could_not_serve.coverage == "unmatched"
    assert _warnings(asked_for_nothing) == []


def test_an_approximated_region_is_marked_as_approximated() -> None:
    query = resolve_target(
        TargetRequest(
            regions=[
                RequestedRegion(
                    label="China", country_code="CN", culture_tag=CultureTag.ASIAN
                )
            ]
        )
    )

    assert query.coverage == "approximated"


def test_a_partly_covered_target_keeps_what_it_can_and_warns_about_the_rest() -> None:
    query = resolve_target(
        TargetRequest(
            regions=[
                RequestedRegion(label="the US", country_code="US"),
                RequestedRegion(label="Nigeria", country_code="NG"),
            ]
        )
    )

    assert query.countries == (Locale.US,)
    assert len(_warnings(query)) == 1


def test_naming_no_region_draws_from_every_seeded_country() -> None:
    """Empty `countries` has to mean "no coverage", so the global rung fills them in
    explicitly rather than leaving the filter off — otherwise the two cases would be
    the same value and retrieval could not tell them apart."""
    query = resolve_target(TargetRequest())

    assert set(query.countries) == set(Locale)
    assert _warnings(query) == []
    assert len(_readings(query)) == 1


def test_one_country_reached_twice_appears_once() -> None:
    query = resolve_target(
        TargetRequest(
            regions=[
                RequestedRegion(label="Japan", country_code="JP"),
                RequestedRegion(
                    label="China", country_code="CN", culture_tag=CultureTag.ASIAN
                ),
            ]
        )
    )

    assert query.countries == (Locale.JP,)


def test_an_age_range_outside_the_pool_is_narrowed_and_flagged() -> None:
    query = resolve_target(TargetRequest(min_age=13, max_age=30))

    assert (query.min_age, query.max_age) == (MIN_PERSONA_AGE, 30)
    assert len(_warnings(query)) == 1


def test_an_age_range_the_pool_covers_passes_through_silently() -> None:
    query = resolve_target(TargetRequest(min_age=40, max_age=49))

    assert (query.min_age, query.max_age) == (40, 49)
    assert _warnings(query) == []


def test_an_unbounded_age_request_takes_the_pool_s_own_bounds() -> None:
    query = resolve_target(TargetRequest())

    assert (query.min_age, query.max_age) == (MIN_PERSONA_AGE, MAX_PERSONA_AGE)
    assert _warnings(query) == []


def test_an_open_upper_bound_is_not_a_narrowing() -> None:
    """Caught live: "over 50" asks for nothing above, so answering 51-100 is exactly
    what was asked. Warning about it trains the customer to ignore the warnings."""
    query = resolve_target(TargetRequest(min_age=51))

    assert (query.min_age, query.max_age) == (51, MAX_PERSONA_AGE)
    assert _warnings(query) == []


def test_an_open_lower_bound_is_not_a_narrowing() -> None:
    query = resolve_target(TargetRequest(max_age=30))

    assert (query.min_age, query.max_age) == (MIN_PERSONA_AGE, 30)
    assert _warnings(query) == []


def test_an_open_lower_bound_below_the_pool_is_still_flagged() -> None:
    """ "under 18" states no floor, so nothing is clamped — but the span it leaves
    matches nobody, and that has to be said."""
    query = resolve_target(TargetRequest(max_age=17))

    assert query.min_age > query.max_age
    assert len(_warnings(query)) == 1


def test_an_upper_bound_above_the_pool_is_flagged() -> None:
    query = resolve_target(TargetRequest(min_age=40, max_age=120))

    assert (query.min_age, query.max_age) == (40, MAX_PERSONA_AGE)
    assert len(_warnings(query)) == 1


def test_an_age_range_the_pool_cannot_reach_at_all_is_left_empty() -> None:
    """Clamping "under 18" leaves 18-17, which matches nobody. That is the right
    answer, and it must not be widened into "everybody" by dropping the filter."""
    query = resolve_target(TargetRequest(min_age=13, max_age=17))

    assert query.min_age > query.max_age
    assert len(_warnings(query)) == 1


def test_income_bands_expand_into_the_quintiles_they_cover() -> None:
    query = resolve_target(TargetRequest(income_bands=["lower", "upper"]))

    assert query.income_quintiles == (1, 2, 4, 5)


def test_no_income_band_means_no_income_filter() -> None:
    assert resolve_target(TargetRequest()).income_quintiles == ()


def test_traits_render_into_the_summary_s_own_words() -> None:
    query = resolve_target(
        TargetRequest(
            traits=[
                TraitRequest(
                    trait="neuroticism",
                    level=TraitLevel.HIGH,
                    source_phrase="cautious",
                )
            ]
        )
    )

    assert query.disposition == _HIGH_NEUROTICISM


def test_a_target_with_no_traits_has_no_vector_half() -> None:
    assert resolve_target(TargetRequest()).disposition == ""


def test_the_trait_reading_is_shown_back_with_the_words_it_came_from() -> None:
    query = resolve_target(
        TargetRequest(
            traits=[
                TraitRequest(
                    trait="conscientiousness",
                    level=TraitLevel.HIGH,
                    source_phrase="budget-conscious",
                )
            ]
        )
    )

    (reading,) = [m for m in _readings(query) if "conscientiousness" in m]
    assert "budget-conscious" in reading
    assert "high" in reading


def test_one_trait_named_twice_keeps_the_first_and_warns() -> None:
    """A contradictory target is exactly where a silent last-wins would mislead."""
    query = resolve_target(
        TargetRequest(
            traits=[
                TraitRequest(
                    trait="extraversion",
                    level=TraitLevel.HIGH,
                    source_phrase="outgoing",
                ),
                TraitRequest(
                    trait="extraversion", level=TraitLevel.LOW, source_phrase="private"
                ),
            ]
        )
    )

    assert query.disposition == "outgoing and energetic, at ease around other people"
    assert "extraversion" in _warnings(query)[0]


def test_an_unmappable_attribute_is_warned_about_not_dropped() -> None:
    """An out-of-coverage attribute is surfaced exactly like an out-of-coverage
    region, because a panel matched on the remaining words looks targeted and is
    not."""
    query = resolve_target(TargetRequest(unmapped=["gamers", "vegan"]))

    (warning,) = _warnings(query)
    assert "gamers" in warning
    assert "vegan" in warning


class StubTranslator:
    """A TargetTranslator double — no network, and it records what it was asked."""

    def __init__(self, request: TargetRequest) -> None:
        self._request = request
        self.descriptions: list[str] = []

    def translate(self, *, description: str) -> TargetRequest:
        self.descriptions.append(description)
        return self._request


class CountingEmbedder:
    """An Embedder double that counts calls, since each one is a paid request."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[1.0] + [0.0] * (DIM - 1) for _ in texts]


_JAPAN = TargetRequest(regions=[RequestedRegion(label="Japan", country_code="JP")])


def test_select_panel_passes_the_description_to_the_translator(conn) -> None:
    translator = StubTranslator(_JAPAN)

    select_panel(
        conn,
        "Japanese homeowners",
        size=5,
        translator=translator,
        embedder=CountingEmbedder(),
    )

    assert translator.descriptions == ["Japanese homeowners"]


def test_select_panel_retrieves_only_matching_personas(conn) -> None:
    persist_pool(
        conn,
        [
            make_assembled(make_persona(id_="JP-00000", country="JP")),
            make_assembled(make_persona(id_="US-00000", country="US")),
        ],
    )

    selection = select_panel(
        conn,
        "Japan",
        size=5,
        translator=StubTranslator(_JAPAN),
        embedder=CountingEmbedder(),
    )

    assert [p.id for p in selection.panel] == ["JP-00000"]


def test_a_target_with_no_temperament_is_never_embedded(conn) -> None:
    """The embedding is a paid call, and there is nothing to rank by."""
    embedder = CountingEmbedder()

    select_panel(
        conn, "Japan", size=5, translator=StubTranslator(_JAPAN), embedder=embedder
    )

    assert embedder.texts == []


def test_a_target_with_temperament_embeds_the_rendered_phrases(conn) -> None:
    """What is embedded has to be the summary's own wording, not the customer's —
    the query is compared against text written in that vocabulary."""
    embedder = CountingEmbedder()
    request = TargetRequest(
        regions=[RequestedRegion(label="Japan", country_code="JP")],
        traits=[
            TraitRequest(
                trait="neuroticism", level=TraitLevel.HIGH, source_phrase="anxious"
            )
        ],
    )

    select_panel(
        conn,
        "anxious Japanese",
        size=5,
        translator=StubTranslator(request),
        embedder=embedder,
    )

    assert embedder.texts == [_HIGH_NEUROTICISM]


def test_an_unservable_region_still_draws_a_panel_from_the_whole_pool(conn) -> None:
    """The fallback means there is a real panel to rank, so the disposition is worth
    embedding after all — the temperament half of the target is still servable even
    when the geography is not."""
    persist_pool(conn, [make_assembled(make_persona(id_="JP-00000", country="JP"))])
    embedder = CountingEmbedder()
    request = TargetRequest(
        regions=[RequestedRegion(label="Nigeria", country_code="NG")],
        traits=[
            TraitRequest(
                trait="openness", level=TraitLevel.HIGH, source_phrase="curious"
            )
        ],
    )

    selection = select_panel(
        conn,
        "curious Nigerians",
        size=5,
        translator=StubTranslator(request),
        embedder=embedder,
    )

    assert [p.id for p in selection.panel] == ["JP-00000"]
    assert len(embedder.texts) == 1
    assert any(n.severity == "warning" for n in selection.notices)


def test_the_selection_carries_the_query_s_own_notices(conn) -> None:
    """One place to read notices from, so a caller cannot show the retrieval's and
    forget the translation's."""
    persist_pool(conn, [make_assembled(make_persona(id_="JP-00000", country="JP"))])
    request = TargetRequest(
        regions=[RequestedRegion(label="Japan", country_code="JP")],
        unmapped=["gamers"],
    )

    selection = select_panel(
        conn,
        "Japanese gamers",
        size=1,
        translator=StubTranslator(request),
        embedder=CountingEmbedder(),
    )

    assert selection.query.notices
    assert selection.notices[: len(selection.query.notices)] == selection.query.notices


def test_a_thin_panel_is_reported_as_a_shortfall(conn) -> None:
    """At n=200 this changes what the verdict can say, so it cannot be silent."""
    persist_pool(
        conn,
        [
            make_assembled(make_persona(id_=f"JP-{i:05d}", country="JP"))
            for i in range(3)
        ],
    )

    selection = select_panel(
        conn,
        "Japan",
        size=200,
        translator=StubTranslator(_JAPAN),
        embedder=CountingEmbedder(),
    )

    assert len(selection.panel) == 3
    (shortfall,) = [n.message for n in selection.notices if "3" in n.message]
    assert "200" in shortfall


def test_a_full_panel_reports_no_shortfall(conn) -> None:
    persist_pool(
        conn,
        [
            make_assembled(make_persona(id_=f"JP-{i:05d}", country="JP"))
            for i in range(3)
        ],
    )

    selection = select_panel(
        conn,
        "Japan",
        size=3,
        translator=StubTranslator(_JAPAN),
        embedder=CountingEmbedder(),
    )

    assert selection.notices == selection.query.notices


def test_the_same_target_draws_the_same_panel_twice(conn) -> None:
    """Reproducibility at the level a customer sees it: one target, one panel."""
    persist_pool(
        conn,
        [
            make_assembled(make_persona(id_=f"JP-{i:05d}", country="JP"))
            for i in range(20)
        ],
    )

    def draw() -> list[str]:
        return [
            p.id
            for p in select_panel(
                conn,
                "Japan",
                size=5,
                translator=StubTranslator(_JAPAN),
                embedder=CountingEmbedder(),
            ).panel
        ]

    assert draw() == draw()


def test_the_countries_the_panel_came_from_are_always_stated() -> None:
    """A place the pool cannot resolve finer than its country — a state, a city — is
    answered with the whole country. Saying only that the place was dropped leaves the
    customer not knowing who did vote, and the translator cannot be relied on to say
    it, so this notice is emitted in code for every panel."""
    query = resolve_target(
        TargetRequest(
            regions=[RequestedRegion(label="Ohio", country_code="US")],
            unmapped=["Ohio"],
        )
    )

    assert query.countries == (Locale.US,)
    assert "Ohio" in _warnings(query)[0]
    assert [m for m in _readings(query) if "United States" in m]
