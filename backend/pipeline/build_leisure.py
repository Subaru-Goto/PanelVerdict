"""Stage 1 — build a country's leisure profile table from its time-use survey.

One keyless source per country, mirroring `build_oecd`. Germany comes from
Eurostat's HETUS 2020 round (`tus_20age`, the Destatis ZVE 2022 fieldwork) as
JSON-stat; Japan from 社会生活基本調査 2021 table 1-1, which e-Stat serves as a
spreadsheet without an application ID (its CSV and JSON endpoints need one).

Every emitted row cites the table and activity it came from. Published values are
used wherever they exist; anything derived is declared in `imputations`, and any
category the survey cannot separate is declared in `unsupported` — both committed
beside the data. Design: issues/006i.
"""

import csv
import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from openpyxl import load_workbook
from pydantic import BaseModel, Field

from app.schemas import LeisureCategory, Locale

_Gender = Literal["male", "female"]
_GENDERS: tuple[_Gender, ...] = ("male", "female")

_Unit = Literal["minutes", "participant_minutes", "rates"]

# --- Germany: Eurostat acl18 activity codes ---------------------------------
# A category needs more than one code only where the survey splits finer than
# the pool does; those are the ones whose participation rate has to be derived
# rather than read.
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

_EUROSTAT_UNSUPPORTED: dict[LeisureCategory, str] = {
    LeisureCategory.HOBBIES_AMUSEMENTS: (
        "not a Eurostat category: acl18 publishes games, reading, computer use, "
        "arts and gardening separately, so the coarse bucket is only meaningful "
        "for surveys that do not split them (Japan)"
    ),
}

_EUROSTAT_BASE = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tus_20age"
)
_EUROSTAT_CITATION = "eurostat:tus_20age"
_EUROSTAT_SEX: dict[str, _Gender] = {"M": "male", "F": "female"}

# Dimensions we index across; every other dimension must be pinned to one value
# by the query, or the flat value index below would silently mis-map.
_INDEXED_DIMS = ("sex", "acl18", "unit")

# --- Japan: 社会生活基本調査 2021 diary activities ----------------------------
# Keyed on the sheet's own English headers, so nothing here depends on matching
# Japanese text. Each category maps to exactly one activity: the diary's leisure
# taxonomy is coarser than the pool's, never finer, so Japan never aggregates.
_ESTAT_ACTIVITIES: dict[LeisureCategory, tuple[str, ...]] = {
    LeisureCategory.TV_MEDIA: (
        "Watching TV, listening to the radio, reading newspapers or magazines",
    ),
    LeisureCategory.HOBBIES_AMUSEMENTS: ("Hobbies and amusements",),
    LeisureCategory.SPORTS_EXERCISE: ("Sports",),
    LeisureCategory.VOLUNTEERING: ("Volunteer and social activities",),
    LeisureCategory.SOCIALIZING: ("Social life",),
}

_ESTAT_UNSUPPORTED: dict[LeisureCategory, str] = {
    LeisureCategory.GAMES: (
        "inside 趣味・娯楽 (hobbies_amusements); the diary does not separate it"
    ),
    LeisureCategory.READING: (
        "split across two diary activities and recoverable from neither: "
        "newspapers and magazines sit inside tv_media, books inside 趣味・娯楽"
    ),
    LeisureCategory.COMPUTER_LEISURE: (
        "inside 趣味・娯楽 (hobbies_amusements); the diary does not separate it"
    ),
    LeisureCategory.ARTS_HOBBIES: (
        "inside 趣味・娯楽 (hobbies_amusements), which also covers games, books "
        "and computer use — reporting it under this name would mean something "
        "much broader here than it does for Germany"
    ),
    LeisureCategory.GARDENING_PETS: (
        "not a diary activity: gardening falls under 趣味・娯楽 or 家事 depending "
        "on whether the respondent treats it as a pastime or a chore"
    ),
    LeisureCategory.GOING_OUT: (
        "not a diary activity: outings are coded to 趣味・娯楽 or 交際・付き合い "
        "by purpose, with no published split"
    ),
    LeisureCategory.OUTDOOR_WALKING: (
        "inside スポーツ (sports_exercise), which counts ウォーキング・軽い体操; "
        "Eurostat publishes walking apart from other sport, Japan does not"
    ),
}

_ESTAT_URL = (
    "https://www.e-stat.go.jp/stat-search/file-download"
    "?statInfId=000032262854&fileKind=0"
)
_ESTAT_CITATION = "e-stat:shakai-seikatsu-2021:table1-1"
_ESTAT_SEX: dict[str, _Gender] = {"男": "male", "女": "female"}

# The sheet lays the three metrics side by side over one repeated set of activity
# headers, so these labels are what tell a duration apart from a percentage.
_ESTAT_BLOCK_UNITS: dict[str, _Unit] = {
    "総平均時間": "minutes",
    "行動者平均時間": "participant_minutes",
    "行動者率": "rates",
}

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
    gender: _Gender
    participation_rate: float = Field(gt=0, le=1)
    participant_minutes: float = Field(gt=0)
    source: str


class UnsupportedCategory(BaseModel):
    """A category this country's survey cannot fill, and why it cannot."""

    category: LeisureCategory
    reason: str = Field(min_length=1)


class LeisureBuildResult(BaseModel):
    """A country's built leisure table, the fidelity it was built at, and the
    categories its survey does not publish."""

    country: Locale
    rows: list[LeisureRow]
    imputations: list[str]
    unsupported: list[UnsupportedCategory]


@dataclass(frozen=True)
class SurveyCells:
    """One survey's published cells, split by unit so each stays its own type.

    Keys are (gender, activity). Keeping the three units apart means callers
    never have to coerce a duration string and a percentage out of one map.
    """

    minutes: dict[tuple[str, str], int]
    participant_minutes: dict[tuple[str, str], int]
    rates: dict[tuple[str, str], float]

    def record(self, unit: _Unit, key: tuple[str, str], value: float) -> None:
        if unit == "minutes":
            self.minutes[key] = int(value)
        elif unit == "participant_minutes":
            self.participant_minutes[key] = int(value)
        else:
            self.rates[key] = value / 100


def _eurostat_url(country: Locale) -> str:
    return f"{_EUROSTAT_BASE}?format=JSON&lang=en&geo={country.value}&age=TOTAL"


def _hhmm_to_minutes(value: str) -> int:
    """Published durations come as "h:mm" strings, not numbers."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def parse_jsonstat(text: str) -> SurveyCells:
    """Flatten a JSON-stat payload into per-unit maps keyed by (gender, activity).

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
        gender = _EUROSTAT_SEX.get(sex)
        if gender is None:
            continue
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
                key = (gender, activity)
                if unit == "TIME_SP":
                    cells.minutes[key] = _hhmm_to_minutes(raw)
                elif unit == "PTP_TIME":
                    cells.participant_minutes[key] = _hhmm_to_minutes(raw)
                elif unit == "PTP_RT":
                    cells.rates[key] = float(raw) / 100
    return cells


def _cell_text(value: object) -> str:
    """Header cells carry line breaks and furigana, so collapse whitespace before
    comparing against the published labels."""
    return " ".join(str(value).split()) if value is not None else ""


def parse_estat_table(payload: bytes) -> SurveyCells:
    """Flatten e-Stat table 1-1 into per-unit maps keyed by (gender, activity).

    Nothing is addressed by row or column number. The sheet repeats one set of
    activity headers under three metric blocks laid out side by side, so which
    block a column belongs to is resolved from the unit labels above it — read
    positionally, a shifted column would return a percentage as a duration, the
    same silent failure Eurostat's ignored `unit` filter produced.
    """
    workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    try:
        grid = [
            list(row)
            for row in workbook[workbook.sheetnames[0]].iter_rows(values_only=True)
        ]
    finally:
        workbook.close()

    blocks: dict[int, _Unit] = {}
    for row in grid:
        labelled = {
            col: unit
            for col, value in enumerate(row)
            for label, unit in _ESTAT_BLOCK_UNITS.items()
            if _cell_text(value).startswith(label)
        }
        # Distinct units, not just three hits: the sheet's title line repeats
        # "総平均時間・行動者平均時間・行動者率" once per block, and those cells
        # would otherwise pass as three block starts that are all the same unit.
        units = set(labelled.values())
        if len(labelled) == len(units) == len(_ESTAT_BLOCK_UNITS):
            blocks = labelled
            break
    if not blocks:
        raise ValueError(
            "no row carries all three metric-block labels "
            f"({', '.join(_ESTAT_BLOCK_UNITS)}); the sheet layout has changed"
        )

    wanted = {name for names in _ESTAT_ACTIVITIES.values() for name in names}
    columns: dict[str, list[int]] = {}
    for row in grid:
        found: dict[str, list[int]] = {}
        for col, value in enumerate(row):
            text = _cell_text(value)
            if text in wanted:
                found.setdefault(text, []).append(col)
        if set(found) == wanted:
            columns = found
            break
    if not columns:
        raise ValueError(
            f"no row carries every mapped activity header; expected {sorted(wanted)}"
        )
    for activity, cols in columns.items():
        if len(cols) != len(_ESTAT_BLOCK_UNITS):
            raise ValueError(
                f"{activity!r} spans {len(cols)} columns, expected one per "
                f"metric block ({len(_ESTAT_BLOCK_UNITS)})"
            )

    # The sex label sits on the first row of its block only, so the row carrying
    # a bare 男/女 with no age beside it is that sex's all-ages row.
    gender_rows: dict[_Gender, list[object]] = {}
    for row in grid:
        for col, value in enumerate(row):
            gender = _ESTAT_SEX.get(_cell_text(value))
            age = _cell_text(row[col + 1]) if col + 1 < len(row) else ""
            if gender is None or age:
                continue
            if gender in gender_rows and gender_rows[gender] is not row:
                raise ValueError(f"more than one all-ages row for {gender}")
            gender_rows[gender] = row
            break  # the sex/age pair is repeated once per metric block
    absent = [gender for gender in _GENDERS if gender not in gender_rows]
    if absent:
        raise ValueError(f"no all-ages row found for {absent}")

    boundaries = sorted(blocks)
    cells = SurveyCells(minutes={}, participant_minutes={}, rates={})
    for gender, row in gender_rows.items():
        for activity, cols in columns.items():
            for col in cols:
                preceding = [start for start in boundaries if start <= col]
                if not preceding:
                    raise ValueError(
                        f"{activity!r} column {col} precedes every metric block"
                    )
                value = row[col]
                if not isinstance(value, int | float):
                    raise ValueError(
                        f"{gender} {activity!r} reads {value!r}, not a number"
                    )
                cells.record(blocks[max(preceding)], (gender, activity), value)
    return cells


def _leisure_rows(
    cells: SurveyCells,
    mapping: dict[LeisureCategory, tuple[str, ...]],
    citation: str,
) -> tuple[list[LeisureRow], list[LeisureCategory]]:
    """Rows for every mapped category, plus the categories whose rate had to be
    derived because the survey publishes no figure for the union.

    A single-activity category is read straight off the survey. An aggregated one
    has no published union, so minutes are summed and the rate is taken as the
    independence union — the same person appears under several activities, which
    rules out adding rates.
    """
    rows: list[LeisureRow] = []
    derived: list[LeisureCategory] = []
    for category, keys in mapping.items():
        if len(keys) > 1:
            derived.append(category)
        for gender in _GENDERS:
            if len(keys) == 1:
                rate = cells.rates[(gender, keys[0])]
                participant_minutes = float(
                    cells.participant_minutes[(gender, keys[0])]
                )
            else:
                not_participating = 1.0
                for key in keys:
                    not_participating *= 1 - cells.rates[(gender, key)]
                rate = 1 - not_participating
                participant_minutes = (
                    sum(cells.minutes[(gender, key)] for key in keys) / rate
                )
            rows.append(
                LeisureRow(
                    category=category,
                    gender=gender,
                    participation_rate=rate,
                    participant_minutes=participant_minutes,
                    source=f"{citation}:{'+'.join(keys)}",
                )
            )
    return rows, derived


def _declare_coverage(
    mapping: dict[LeisureCategory, tuple[str, ...]],
    reasons: dict[LeisureCategory, str],
) -> list[UnsupportedCategory]:
    """Check every category is either filled or explained, and return the
    explanations.

    This is what keeps a union vocabulary honest: adding an enum member without
    deciding what each country does about it fails the build instead of quietly
    producing a country whose table is short a column.
    """
    both = set(mapping) & set(reasons)
    if both:
        raise ValueError(
            "categories both mapped and declared unsupported: "
            f"{sorted(category.value for category in both)}"
        )
    unaccounted = [
        category.value
        for category in LeisureCategory
        if category not in mapping and category not in reasons
    ]
    if unaccounted:
        raise ValueError(
            f"categories neither mapped nor declared unsupported: {unaccounted}"
        )
    return [
        UnsupportedCategory(category=category, reason=reason)
        for category, reason in reasons.items()
    ]


def _build_germany(fetch: Callable[[str], bytes]) -> LeisureBuildResult:
    cells = parse_jsonstat(fetch(_eurostat_url(Locale.DE)).decode())
    rows, derived = _leisure_rows(cells, _EUROSTAT_CODES, _EUROSTAT_CITATION)

    imputations = [
        "age is not conditioned: the query pins age=TOTAL, though tus_20age "
        "publishes 16 age bands for DE"
    ]
    if derived:
        imputations.append(
            "participation rate for aggregated categories "
            f"({', '.join(category.value for category in derived)}) is the "
            "independence union 1-prod(1-r), and their participant minutes are "
            "population minutes / that rate; every other category is read from "
            "the published PTP_RT and PTP_TIME cells"
        )
    return LeisureBuildResult(
        country=Locale.DE,
        rows=rows,
        imputations=imputations,
        unsupported=_declare_coverage(_EUROSTAT_CODES, _EUROSTAT_UNSUPPORTED),
    )


def _build_japan(fetch: Callable[[str], bytes]) -> LeisureBuildResult:
    cells = parse_estat_table(fetch(_ESTAT_URL))
    rows, derived = _leisure_rows(cells, _ESTAT_ACTIVITIES, _ESTAT_CITATION)
    assert not derived, "every Japanese category maps to a single diary activity"

    return LeisureBuildResult(
        country=Locale.JP,
        rows=rows,
        imputations=[
            "age is not conditioned: the all-ages row is read, though table 1-1 "
            "publishes 17 age bands",
            "rates are diary-day rates (主行動, primary activity only), so they "
            "are far lower than the past-year 行動者率 the survey also publishes "
            "— volunteering is 1.8% of men on a given day against ~26% in a year",
            "socializing is 交際・付き合い, which covers visits and ceremonies but "
            "not conversation at home; Eurostat's socializing does include it, so "
            "the two countries' figures are not comparable to each other",
        ],
        unsupported=_declare_coverage(_ESTAT_ACTIVITIES, _ESTAT_UNSUPPORTED),
    )


def build_leisure(
    country: Locale, *, fetch: Callable[[str], bytes]
) -> LeisureBuildResult:
    """Build one country's leisure table: participation rate + participant minutes
    per (category, gender), for the categories that country's survey publishes.
    """
    if country is Locale.DE:
        return _build_germany(fetch)
    if country is Locale.JP:
        return _build_japan(fetch)
    raise NotImplementedError(
        "US needs ATUS 2024 Table A-1 via the archive mirror (bls.gov 403s "
        "scripted clients) — slice 1b, see issues/006i"
    )


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
            {
                "country": result.country.value,
                "imputations": result.imputations,
                "unsupported": [
                    {"category": entry.category.value, "reason": entry.reason}
                    for entry in result.unsupported
                ],
            },
            indent=2,
        )
        + "\n"
    )


def _http_fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (panelverdict pipeline)"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


if __name__ == "__main__":
    import sys

    target = Locale(sys.argv[1])
    dest = Path(__file__).parents[1] / "app" / "data" / "leisure"
    built = build_leisure(target, fetch=_http_fetch)
    write_leisure(built, dest)
    print(f"wrote {target.value}: {len(built.rows)} rows")
    for note in built.imputations:
        print(f"  declared: {note}")
    for entry in built.unsupported:
        print(f"  unsupported: {entry.category.value} — {entry.reason}")
