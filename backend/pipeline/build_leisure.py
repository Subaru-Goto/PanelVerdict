"""Stage 1 — build a country's leisure profile table from its time-use survey.

One keyless API per country, queried by country code, mirroring `build_oecd`.
Germany comes from Eurostat's HETUS 2020 round (`tus_20age`, the Destatis ZVE
2022 fieldwork) as machine-readable JSON-stat. The US and Japan surveys are not
served as APIs and land in follow-up slices.

Every emitted row cites the dataset and activity codes it came from, and any
value that is derived rather than published is declared in `imputations`.
Design: issues/006i.
"""

import csv
import json
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import LeisureCategory, Locale

# Harmonized category -> Eurostat acl18 activity codes. Several categories need
# more than one code because the survey splits finer than the pool does (the
# coarsest of the three national taxonomies sets the granularity).
_EUROSTAT_CODES: dict[LeisureCategory, tuple[str, ...]] = {
    LeisureCategory.TV_MEDIA: ("AC821", "AC831"),
    LeisureCategory.SOCIALIZING: ("AC511", "AC512_513_519", "AC514-516"),
    LeisureCategory.GAMES: ("AC733-735",),
    LeisureCategory.SPORTS_EXERCISE: ("AC6_X_611", "AC611"),
    LeisureCategory.READING: ("AC812", "AC81_X_812"),
    LeisureCategory.ARTS_HOBBIES: ("AC711_712_719_731_732_739",),
    LeisureCategory.COMPUTER_LEISURE: ("AC72",),
    LeisureCategory.GARDENING_PETS: ("AC34",),
    LeisureCategory.GOING_OUT: ("AC52",),
    LeisureCategory.VOLUNTEERING: ("AC4",),
}

_SEX_CODE: dict[str, str] = {"male": "M", "female": "F"}

_EUROSTAT_BASE = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tus_20age"
)
_DATASET = "eurostat:tus_20age"

# Dimensions we index across; every other dimension must be pinned to one value
# by the query, or the flat value index below would silently mis-map.
_INDEXED_DIMS = ("sex", "acl18", "unit")

_LEISURE_COLUMNS = [
    "category",
    "gender",
    "participation_rate",
    "participant_minutes",
    "source",
]


class LeisureRow(BaseModel):
    """One (category, gender) cell of a country's committed leisure table."""

    category: LeisureCategory
    gender: Literal["male", "female"]
    participation_rate: float = Field(gt=0, le=1)
    participant_minutes: float = Field(gt=0)
    source: str


class LeisureBuildResult(BaseModel):
    """A country's built leisure table plus the fidelity it was built at."""

    country: Locale
    rows: list[LeisureRow]
    imputations: list[str]


def _eurostat_url(country: Locale) -> str:
    return f"{_EUROSTAT_BASE}?format=JSON&lang=en&geo={country.value}&age=TOTAL"


def _hhmm_to_minutes(value: str) -> int:
    """Published durations come as "h:mm" strings, not numbers."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def parse_jsonstat(text: str) -> dict[tuple[str, str, str], float | str]:
    """Flatten a JSON-stat payload into {(sex, activity, unit): value}.

    JSON-stat stores values against a single row-major index over all
    dimensions, so strides are derived from `size` rather than assumed — a
    dimension reordering upstream would otherwise mis-map every cell silently.
    """
    payload = json.loads(text)
    dims: list[str] = payload["id"]
    sizes: list[int] = payload["size"]
    strides: dict[str, int] = {}
    stride = 1
    for dim, size in zip(reversed(dims), reversed(sizes)):
        strides[dim] = stride
        stride *= size
    unpinned = [
        dim
        for dim, size in zip(dims, sizes)
        if size > 1 and dim not in _INDEXED_DIMS
    ]
    if unpinned:
        raise ValueError(f"query must pin one value per dimension; got {unpinned}")

    index = {dim: payload["dimension"][dim]["category"]["index"] for dim in _INDEXED_DIMS}
    values = payload["value"]
    cells: dict[tuple[str, str, str], float | str] = {}
    for sex, sex_i in index["sex"].items():
        for activity, activity_i in index["acl18"].items():
            for unit, unit_i in index["unit"].items():
                flat = (
                    sex_i * strides["sex"]
                    + activity_i * strides["acl18"]
                    + unit_i * strides["unit"]
                )
                value = values.get(str(flat))
                if value is not None:
                    cells[(sex, activity, unit)] = value
    return cells


def build_leisure(
    country: Locale, *, fetch: Callable[[str], str]
) -> LeisureBuildResult:
    """Build one country's leisure table: participation rate + participant minutes
    per (harmonized category, gender).

    Minutes across a category's activity codes add, but published participation
    rates cannot — the same person appears in several codes. The union is taken
    under an independence assumption and declared.
    """
    if country is not Locale.DE:
        raise NotImplementedError(
            f"{country.value} has no time-use API; ATUS (US) and 社会生活基本調査 "
            "(JP) land in follow-up slices — see issues/006i"
        )
    cells = parse_jsonstat(fetch(_eurostat_url(country)))

    rows: list[LeisureRow] = []
    approximated: list[str] = []
    for category, codes in _EUROSTAT_CODES.items():
        if len(codes) > 1:
            approximated.append(category.value)
        for gender, sex in _SEX_CODE.items():
            minutes = sum(
                _hhmm_to_minutes(str(cells[(sex, code, "TIME_SP")])) for code in codes
            )
            not_participating = 1.0
            for code in codes:
                not_participating *= 1 - float(cells[(sex, code, "PTP_RT")]) / 100
            rate = 1 - not_participating
            rows.append(
                LeisureRow(
                    category=category,
                    gender=gender,
                    participation_rate=rate,
                    participant_minutes=minutes / rate,
                    source=f"{_DATASET}:{'+'.join(codes)}",
                )
            )

    imputations = []
    if approximated:
        imputations.append(
            "participation rate for multi-code categories "
            f"({', '.join(approximated)}) is the independence union "
            "1-prod(1-r), since published rates overlap and cannot be summed"
        )
    return LeisureBuildResult(country=country, rows=rows, imputations=imputations)


def write_leisure(result: LeisureBuildResult, dest_dir: Path) -> None:
    """Write the committed per-country CSV the sampler reads."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{result.country.value.lower()}.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_LEISURE_COLUMNS)
        for row in result.rows:
            writer.writerow(
                [
                    row.category.value,
                    row.gender,
                    f"{row.participation_rate:.4f}",
                    f"{row.participant_minutes:.1f}",
                    row.source,
                ]
            )


def _http_fetch(url: str) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (panelverdict pipeline)"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode()


if __name__ == "__main__":
    import sys

    target = Locale(sys.argv[1])
    dest = Path(__file__).parents[1] / "app" / "data" / "leisure"
    built = build_leisure(target, fetch=_http_fetch)
    write_leisure(built, dest)
    print(f"wrote {target.value}: {len(built.rows)} rows")
    for note in built.imputations:
        print(f"  imputed: {note}")
