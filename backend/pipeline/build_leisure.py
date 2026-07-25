"""Stage 1 — build a country's leisure profile table from its time-use survey.

One keyless API per country, queried by country code, mirroring `build_oecd`.
Germany comes from Eurostat's HETUS 2020 round (`tus_20age`, the Destatis ZVE
2022 fieldwork) as machine-readable JSON-stat.

Every emitted row cites the dataset and activity codes it came from. Published
values are used wherever they exist; anything derived is declared in
`imputations` and committed alongside the data. Design: issues/006i.
"""

import csv
import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import LeisureCategory, Locale

# Harmonized category -> Eurostat acl18 activity codes. A category needs more
# than one code only where the survey splits finer than the pool does; those are
# the ones whose participation rate has to be derived rather than read.
_EUROSTAT_CODES: dict[LeisureCategory, tuple[str, ...]] = {
    LeisureCategory.TV_MEDIA: ("AC821", "AC831"),
    LeisureCategory.SOCIALIZING: ("AC511", "AC512_513_519", "AC514-516"),
    LeisureCategory.GAMES: ("AC733-735",),
    LeisureCategory.SPORTS_EXERCISE: ("AC6_X_611",),
    LeisureCategory.OUTDOOR_WALKING: ("AC611",),
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
_CITATION = "eurostat:tus_20age"

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


@dataclass(frozen=True)
class SurveyCells:
    """One survey's published cells, split by unit so each stays its own type.

    Keys are (sex, activity code). Keeping the three units apart means callers
    never have to coerce a duration string and a percentage out of one map.
    """

    minutes: dict[tuple[str, str], int]
    participant_minutes: dict[tuple[str, str], int]
    rates: dict[tuple[str, str], float]


def _eurostat_url(country: Locale) -> str:
    return f"{_EUROSTAT_BASE}?format=JSON&lang=en&geo={country.value}&age=TOTAL"


def _hhmm_to_minutes(value: str) -> int:
    """Published durations come as "h:mm" strings, not numbers."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def parse_jsonstat(text: str) -> SurveyCells:
    """Flatten a JSON-stat payload into per-unit maps keyed by (sex, activity).

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
        dim for dim, size in zip(dims, sizes) if size > 1 and dim not in _INDEXED_DIMS
    ]
    if unpinned:
        raise ValueError(f"query must pin one value per dimension; got {unpinned}")

    index = {
        dim: payload["dimension"][dim]["category"]["index"] for dim in _INDEXED_DIMS
    }
    values = payload["value"]
    cells = SurveyCells(minutes={}, participant_minutes={}, rates={})
    for sex, sex_i in index["sex"].items():
        for activity, activity_i in index["acl18"].items():
            for unit, unit_i in index["unit"].items():
                flat = (
                    sex_i * strides["sex"]
                    + activity_i * strides["acl18"]
                    + unit_i * strides["unit"]
                )
                raw = values.get(str(flat))
                if raw is None:
                    continue
                key = (sex, activity)
                if unit == "TIME_SP":
                    cells.minutes[key] = _hhmm_to_minutes(raw)
                elif unit == "PTP_TIME":
                    cells.participant_minutes[key] = _hhmm_to_minutes(raw)
                elif unit == "PTP_RT":
                    cells.rates[key] = float(raw) / 100
    return cells


def build_leisure(
    country: Locale, *, fetch: Callable[[str], str]
) -> LeisureBuildResult:
    """Build one country's leisure table: participation rate + participant minutes
    per (harmonized category, gender).

    A single-code category is read straight off the survey. An aggregated one has
    no published union, so minutes are summed and the rate is taken as the
    independence union — the same person appears under several codes, which rules
    out adding rates.
    """
    if country is not Locale.DE:
        raise NotImplementedError(
            f"{country.value} has no time-use API: ATUS (US) needs the archive "
            "mirror and 社会生活基本調査 (JP) needs e-Stat detail tables"
        )
    cells = parse_jsonstat(fetch(_eurostat_url(country)))

    rows: list[LeisureRow] = []
    derived: list[str] = []
    for category, codes in _EUROSTAT_CODES.items():
        if len(codes) > 1:
            derived.append(category.value)
        for gender, sex in _SEX_CODE.items():
            if len(codes) == 1:
                rate = cells.rates[(sex, codes[0])]
                participant_minutes = float(cells.participant_minutes[(sex, codes[0])])
            else:
                not_participating = 1.0
                for code in codes:
                    not_participating *= 1 - cells.rates[(sex, code)]
                rate = 1 - not_participating
                participant_minutes = (
                    sum(cells.minutes[(sex, code)] for code in codes) / rate
                )
            rows.append(
                LeisureRow(
                    category=category,
                    gender=gender,
                    participation_rate=rate,
                    participant_minutes=participant_minutes,
                    source=f"{_CITATION}:{'+'.join(codes)}",
                )
            )

    imputations = [
        "age is not conditioned: the query pins age=TOTAL, though tus_20age "
        "publishes 16 age bands for DE"
    ]
    if derived:
        imputations.append(
            f"participation rate for aggregated categories ({', '.join(derived)}) "
            "is the independence union 1-prod(1-r), and their participant minutes "
            "are population minutes / that rate; every other category is read "
            "from the published PTP_RT and PTP_TIME cells"
        )
    return LeisureBuildResult(country=country, rows=rows, imputations=imputations)


def write_leisure(result: LeisureBuildResult, dest_dir: Path) -> None:
    """Write the committed per-country CSV plus its provenance sidecar.

    The sidecar matters: a caveat that only reaches stdout is invisible to
    anyone who later reads the CSV (`build_oecd.write_joint` sets the precedent).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = result.country.value.lower()
    with (dest_dir / f"{stem}.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_LEISURE_COLUMNS)
        writer.writeheader()
        for row in result.rows:
            writer.writerow(
                {
                    "category": row.category.value,
                    "gender": row.gender,
                    "participation_rate": f"{row.participation_rate:.4f}",
                    "participant_minutes": f"{row.participant_minutes:.1f}",
                    "source": row.source,
                }
            )
    (dest_dir / f"{stem}.meta.json").write_text(
        json.dumps(
            {"country": result.country.value, "imputations": result.imputations},
            indent=2,
        )
        + "\n"
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
        print(f"  declared: {note}")
