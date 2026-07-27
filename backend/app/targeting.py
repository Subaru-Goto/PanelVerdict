"""Turn a natural-language target description into an executable panel query.

Two steps, kept apart because only the first one costs money: a model reads the
description into a `TargetRequest` (what was asked for), and `resolve_target` maps
that onto what the pool can actually serve (`TargetQuery`).

Splitting them is what keeps a substitution visible. A request records the country
as named, so the approximating happens here, in code, with a notice attached — rather
than inside a model call, where a panel matched on the remaining words of the query
would be indistinguishable from a targeted one.
"""

from dataclasses import dataclass
from typing import Protocol

import psycopg

from app.persistence import retrieve_panel
from app.schemas import (
    COUNTRY_CULTURE_TAG,
    COUNTRY_NAME,
    INCOME_BAND_QUINTILES,
    MAX_PERSONA_AGE,
    MIN_PERSONA_AGE,
    CoverageRung,
    CultureTag,
    Locale,
    Persona,
    RequestedRegion,
    TargetNotice,
    TargetQuery,
    TargetRequest,
    TraitName,
    TraitRequest,
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
) -> tuple[tuple[Locale, ...], CoverageRung, TargetNotice | None]:
    """One place, down the ladder: the country itself, then its culture tag."""
    exact = _seeded(region.country_code)
    if exact is not None:
        return (exact,), "requested", None

    approximate = _SEEDED_BY_TAG.get(region.culture_tag) if region.culture_tag else None
    if approximate:
        return (
            approximate,
            "approximated",
            _warn(
                f"No {region.label} data; approximating with "
                f"{region.culture_tag.value}-region personas ({_named(approximate)}). "
                "Treat as indicative."
            ),
        )

    return (
        (),
        "unmatched",
        _warn(
            f"No {region.label} data, and no seeded region close enough to stand in "
            "for it."
        ),
    )


def _resolve_regions(
    regions: list[RequestedRegion],
) -> tuple[tuple[Locale, ...], CoverageRung, list[TargetNotice]]:
    """Every named place, plus the whole-pool fallback when none could be served.

    The fallback is deliberately per *query*, not per region: falling back for one
    unservable region would add its neighbours to a panel that the served regions
    could have filled on their own, taking requested personas out to make room for
    unrequested ones.
    """
    if not regions:
        return tuple(Locale), "requested", []

    countries: list[Locale] = []
    notices: list[TargetNotice] = []
    approximated = False
    for region in regions:
        reached, rung, notice = _resolve_region(region)
        countries.extend(country for country in reached if country not in countries)
        approximated = approximated or rung == "approximated"
        if notice is not None:
            notices.append(notice)

    if countries:
        return (
            tuple(countries),
            ("approximated" if approximated else "requested"),
            notices,
        )

    every = tuple(Locale)
    notices.append(
        _warn(
            f"The panel spans the whole pool instead ({_named(every)}), so it is "
            "not matched to the audience described — read it as a check on the "
            "wording rather than on that audience."
        )
    )
    return every, "unmatched", notices


def _resolve_ages(
    min_age: int | None, max_age: int | None
) -> tuple[int, int, list[TargetNotice]]:
    """Clamp the requested span onto the pool's, and say so when that bites.

    Each bound is clamped independently, so a span entirely outside the pool ends up
    inverted and matches nobody. That is the honest answer — widening it back to the
    pool's own span would answer "under 18" with the whole panel.
    """
    low = MIN_PERSONA_AGE if min_age is None else max(min_age, MIN_PERSONA_AGE)
    high = MAX_PERSONA_AGE if max_age is None else min(max_age, MAX_PERSONA_AGE)

    # An unstated bound filled in with the pool's own is not a narrowing: "over 50"
    # asks for nothing above, so answering 51-100 is exactly what was asked.
    narrowed = (min_age is not None and low != min_age) or (
        max_age is not None and high != max_age
    )
    span = f"ages {MIN_PERSONA_AGE}-{MAX_PERSONA_AGE}"
    asked = (
        f"{'any' if min_age is None else min_age}"
        f"-{'any' if max_age is None else max_age}"
    )
    if low > high:
        return low, high, [_warn(f"The pool covers {span}; nobody in it is {asked}.")]
    if narrowed:
        return (
            low,
            high,
            [
                _warn(
                    f"The pool covers {span}, so the requested {asked} became {low}-{high}."
                )
            ],
        )
    return low, high, []


def _resolve_traits(
    requested: list[TraitRequest],
) -> tuple[tuple[TraitRequest, ...], list[TargetNotice]]:
    """One reading per trait, since each becomes a bound on that trait's column.

    Two levels of one trait would filter for both at once and match nobody, so the
    first is kept and the contradiction reported rather than intersected.
    """
    kept: dict[TraitName, TraitRequest] = {}
    conflicts: list[str] = []
    for trait in requested:
        if trait.trait in kept:
            conflicts.append(trait.trait)
            continue
        kept[trait.trait] = trait

    sources = [
        f'{trait.trait}: {trait.level.value} (from "{trait.source_phrase}")'
        for trait in kept.values()
    ]
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
    return tuple(kept.values()), notices


def resolve_target(request: TargetRequest) -> TargetQuery:
    """Map what was asked for onto what the pool can serve, keeping the difference.

    Every gap between the two becomes a notice rather than a silent substitution:
    the panel a customer gets may be narrower, coarser or emptier than the one they
    described, and only the notices distinguish those from a panel that matched.
    """
    countries, coverage, notices = _resolve_regions(request.regions)
    min_age, max_age, age_notices = _resolve_ages(request.min_age, request.max_age)
    traits, trait_notices = _resolve_traits(request.traits)
    notices += age_notices + trait_notices

    if request.unmapped:
        notices.append(
            _warn(
                "The pool holds no data on "
                f"{', '.join(request.unmapped)} — the panel is not matched on that."
            )
        )
    # Stated in code, so that whatever the translator did with the description the
    # customer still learns which countries were in scope. A place the pool cannot
    # resolve below its country — a state, a city — would otherwise be reported only
    # as dropped, never as answered with the whole country.
    #
    # Phrased as the scope searched rather than the panel drawn, because nothing here
    # knows whether anyone matched: the age span may be empty and the remaining
    # filters may exclude everybody. Claiming a panel would put a notice about
    # something that did not happen next to the warning saying so.
    notices.append(_reading(f"Matched against panelists in {_named(countries)}."))

    return TargetQuery(
        countries=countries,
        coverage=coverage,
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
        traits=traits,
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
# run. A caller wanting two independent draws of one target passes its own.
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
    seed: int = PANEL_SEED,
) -> PanelSelection:
    """Natural-language target description → the panel that will vote on it.

    Translate, resolve onto the pool's coverage, then retrieve. One model call, and
    it is the only paid step: everything the description asked for is served by the
    pool's own columns.
    """
    query = resolve_target(translator.translate(description=description))
    panel = retrieve_panel(conn, query, size=size, seed=seed)
    return PanelSelection(
        panel=panel,
        query=query,
        notices=query.notices + _shortfall_notices(panel, size),
    )
