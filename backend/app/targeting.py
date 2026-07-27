"""Turn a natural-language target description into an executable panel query.

Two steps, kept apart because only the first one costs money: a model reads the
description into a `TargetRequest` (what was asked for), and `resolve_target` maps
that onto what the pool can actually serve (`TargetQuery`).

The split is what makes the ticket's "never silent" rule enforceable. A request
records the country as named, so the substitution needed to serve it happens here,
in code, with a notice attached — rather than inside a model call where a panel
matched on the remaining words of the query would be indistinguishable from a
targeted one.
"""

from dataclasses import dataclass
from typing import Protocol

import psycopg

from app.assembly import Embedder
from app.panel import render_trait_phrases
from app.persistence import retrieve_panel
from app.schemas import (
    COUNTRY_CULTURE_TAG,
    COUNTRY_NAME,
    INCOME_BAND_QUINTILES,
    MAX_PERSONA_AGE,
    MIN_PERSONA_AGE,
    CultureTag,
    Locale,
    Persona,
    RequestedRegion,
    TargetNotice,
    TargetQuery,
    TargetRequest,
    TraitLevel,
    TraitName,
)

_SEEDED_BY_TAG: dict[CultureTag, tuple[Locale, ...]] = {
    tag: tuple(
        country
        for country, country_tag in COUNTRY_CULTURE_TAG.items()
        if country_tag == tag
    )
    for tag in CultureTag
}

_NO_MATCH = "No panelists match this target, so no panel was drawn."


class TargetTranslator(Protocol):
    """Reads a target description into a `TargetRequest`. One model call."""

    def translate(self, *, description: str) -> TargetRequest: ...


def _warn(message: str) -> TargetNotice:
    return TargetNotice(severity="warning", message=message)


def _reading(message: str) -> TargetNotice:
    return TargetNotice(severity="reading", message=message)


def _named(countries: tuple[Locale, ...]) -> str:
    return ", ".join(COUNTRY_NAME[country] for country in countries)


def _seeded(country_code: str | None) -> Locale | None:
    """The seeded locale a country code names, if we seeded that country."""
    try:
        return Locale((country_code or "").upper())
    except ValueError:
        return None


def _resolve_region(
    region: RequestedRegion,
) -> tuple[tuple[Locale, ...], TargetNotice | None]:
    """One place, down the ladder: country → culture tag → nothing."""
    exact = _seeded(region.country_code)
    if exact is not None:
        return (exact,), None

    approximate = _SEEDED_BY_TAG.get(region.culture_tag) if region.culture_tag else None
    if approximate:
        return approximate, _warn(
            f"No {region.label} data; approximating with "
            f"{region.culture_tag.value}-region personas ({_named(approximate)}). "
            "Treat as indicative."
        )

    return (), _warn(
        f"No {region.label} data, and no seeded region close enough to stand in "
        "for it. Those personas are missing from the panel."
    )


def _resolve_regions(
    regions: list[RequestedRegion],
) -> tuple[tuple[Locale, ...], list[TargetNotice]]:
    if not regions:
        every = tuple(Locale)
        return every, [
            _reading(
                "No country named, so the panel spans every country in the pool "
                f"({_named(every)})."
            )
        ]

    countries: list[Locale] = []
    notices: list[TargetNotice] = []
    for region in regions:
        reached, notice = _resolve_region(region)
        countries.extend(country for country in reached if country not in countries)
        if notice is not None:
            notices.append(notice)
    return tuple(countries), notices


def _resolve_ages(request: TargetRequest) -> tuple[int, int, list[TargetNotice]]:
    """Clamp the requested span onto the pool's, and say so when that bites.

    Each bound is clamped independently, so a span entirely outside the pool ends up
    inverted and matches nobody. That is the honest answer — widening it back to the
    pool's own span would answer "under 18" with the whole panel.
    """
    low = max(
        request.min_age if request.min_age is not None else MIN_PERSONA_AGE,
        MIN_PERSONA_AGE,
    )
    high = min(
        request.max_age if request.max_age is not None else MAX_PERSONA_AGE,
        MAX_PERSONA_AGE,
    )
    if (request.min_age, request.max_age) == (None, None) or (low, high) == (
        request.min_age,
        request.max_age,
    ):
        return low, high, []

    asked = (
        f"{request.min_age if request.min_age is not None else 'any'}"
        f"-{request.max_age if request.max_age is not None else 'any'}"
    )
    served = "nobody" if low > high else f"{low}-{high}"
    return (
        low,
        high,
        [
            _warn(
                f"The pool covers ages {MIN_PERSONA_AGE}-{MAX_PERSONA_AGE}, so the "
                f"requested {asked} was narrowed to {served}."
            )
        ],
    )


def _resolve_traits(
    request: TargetRequest,
) -> tuple[dict[TraitName, TraitLevel], list[TargetNotice]]:
    levels: dict[TraitName, TraitLevel] = {}
    sources: list[str] = []
    conflicts: list[str] = []
    for trait in request.traits:
        if trait.trait in levels:
            conflicts.append(trait.trait)
            continue
        levels[trait.trait] = trait.level
        sources.append(
            f'{trait.trait}: {trait.level.value} (from "{trait.source_phrase}")'
        )

    notices = (
        []
        if not sources
        else [_reading("Read personality as " + "; ".join(sources) + ".")]
    )
    if conflicts:
        notices.append(
            _warn(
                "The target asks for two different levels of "
                f"{', '.join(dict.fromkeys(conflicts))}; the first reading was used "
                "and the rest ignored."
            )
        )
    return levels, notices


def resolve_target(request: TargetRequest) -> TargetQuery:
    """Map what was asked for onto what the pool can serve, keeping the difference.

    Every gap between the two becomes a notice rather than a silent substitution:
    the panel a customer gets may be narrower, coarser or emptier than the one they
    described, and only the notices distinguish those from a panel that matched.
    """
    countries, notices = _resolve_regions(request.regions)
    min_age, max_age, age_notices = _resolve_ages(request)
    levels, trait_notices = _resolve_traits(request)
    notices += age_notices + trait_notices

    if request.unmapped:
        notices.append(
            _warn(
                "The pool holds no data on "
                f"{', '.join(request.unmapped)} — the panel is not matched on that."
            )
        )
    if not countries:
        notices.append(_warn(_NO_MATCH))

    return TargetQuery(
        countries=countries,
        min_age=min_age,
        max_age=max_age,
        gender=request.gender,
        income_quintiles=tuple(
            sorted(
                {
                    quintile
                    for band in request.income_bands
                    for quintile in INCOME_BAND_QUINTILES[band]
                }
            )
        ),
        education=tuple(dict.fromkeys(request.education)),
        disposition=render_trait_phrases(levels),
        notices=tuple(notices),
    )


@dataclass(frozen=True)
class PanelSelection:
    """The panel a target description drew, and everything needed to read it.

    `notices` is the complete set — it opens with the query's own and adds anything
    the retrieval itself revealed, so a caller has one place to look rather than two
    lists to remember to concatenate.
    """

    panel: list[Persona]
    query: TargetQuery
    notices: tuple[TargetNotice, ...]


# Fixed by default, so the same target description draws the same panel run after
# run — the reproducibility the ticket asks for. A caller wanting two independent
# draws of one target (to measure sample stability) passes its own.
PANEL_SEED = 0


def _shortfall_notices(panel: list[Persona], size: int) -> tuple[TargetNotice, ...]:
    if len(panel) >= size:
        return ()
    if not panel:
        return (_warn(_NO_MATCH),)
    return (
        _warn(
            f"Only {len(panel)} of the {size} panelists asked for match this target, "
            "so the verdict rests on fewer votes and a wider interval."
        ),
    )


def select_panel(
    conn: psycopg.Connection,
    description: str,
    *,
    size: int,
    translator: TargetTranslator,
    embedder: Embedder,
    seed: int = PANEL_SEED,
) -> PanelSelection:
    """Natural-language target description → the panel that will vote on it.

    The whole of 007 in call order: translate, resolve onto the pool's coverage,
    then retrieve. Two model calls at most — one to read the description, one to
    embed the temperament it asked for — and the second is skipped when there is
    nothing to rank or nobody to rank.
    """
    query = resolve_target(translator.translate(description=description))
    if not query.countries:
        # No seeded country survived the ladder, so no persona can match whatever
        # the disposition says. Embedding it would be paying to sort an empty set.
        return PanelSelection(panel=[], query=query, notices=query.notices)

    panel = retrieve_panel(
        conn,
        query,
        size=size,
        seed=seed,
        disposition_embedding=(
            embedder.embed([query.disposition])[0] if query.disposition else None
        ),
    )
    return PanelSelection(
        panel=panel,
        query=query,
        notices=query.notices + _shortfall_notices(panel, size),
    )
