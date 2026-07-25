import csv
from pathlib import Path

import pytest

from app.schemas import LeisureCategory, Locale
from pipeline.build_leisure import (
    _EUROSTAT_CODES,
    _hhmm_to_minutes,
    build_leisure,
    parse_jsonstat,
    write_leisure,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def fake_fetch(url: str) -> str:
    assert "tus_20age" in url and "geo=DE" in url
    return (_FIXTURES / "eurostat_tus_deu.json").read_text()


def _rows_by_key(result):
    return {(row.category, row.gender): row for row in result.rows}


def test_hhmm_to_minutes_parses_published_time_strings() -> None:
    assert _hhmm_to_minutes("2:07") == 127
    assert _hhmm_to_minutes("0:06") == 6


def test_parse_jsonstat_returns_published_cells_by_dimension() -> None:
    cells = parse_jsonstat(fake_fetch("tus_20age?geo=DE"))

    # published values, read straight off the Eurostat table
    assert cells[("M", "AC821", "PTP_RT")] == 73.25
    assert cells[("F", "AC812", "PTP_RT")] == 17.98
    assert cells[("M", "AC821", "TIME_SP")] == "2:12"
    assert cells[("M", "AC821", "PTP_TIME")] == "3:00"


def test_build_leisure_derives_a_single_code_category_exactly() -> None:
    # GAMES maps to AC733-735 alone, so no aggregation approximation applies:
    # males 0:26/day at a 16.78% participation rate -> 26 / 0.1678 = 154.9 min
    row = _rows_by_key(build_leisure(Locale.DE, fetch=fake_fetch))[
        (LeisureCategory.GAMES, "male")
    ]

    assert row.participation_rate == pytest.approx(0.1678, abs=1e-4)
    assert row.participant_minutes == pytest.approx(154.9, abs=0.1)


def test_build_leisure_aggregates_codes_by_independence_union() -> None:
    # TV_MEDIA = AC821 (2:12, 73.25%) + AC831 (0:07, 10.36%) for males.
    # minutes add: 132 + 7 = 139. Rates cannot add (overlapping participants),
    # so the union under independence is 1 - (1-.7325)(1-.1036) = 0.7602,
    # giving 139 / 0.7602 = 182.8 participant minutes — which cross-checks
    # against AC821's own published participation time of 3:00.
    row = _rows_by_key(build_leisure(Locale.DE, fetch=fake_fetch))[
        (LeisureCategory.TV_MEDIA, "male")
    ]

    assert row.participation_rate == pytest.approx(0.7602, abs=1e-4)
    assert row.participant_minutes == pytest.approx(182.8, abs=0.1)


def test_build_leisure_declares_the_union_approximation() -> None:
    result = build_leisure(Locale.DE, fetch=fake_fetch)

    declared = " ".join(result.imputations)
    assert "independence" in declared.lower()
    # only the multi-code categories are approximated; single-code ones are exact
    for category, codes in _EUROSTAT_CODES.items():
        assert (category.value in declared) is (len(codes) > 1)


def test_build_leisure_covers_every_category_for_both_genders() -> None:
    result = build_leisure(Locale.DE, fetch=fake_fetch)

    assert result.country is Locale.DE
    assert len(result.rows) == len(LeisureCategory) * 2
    assert set(_rows_by_key(result)) == {
        (category, gender)
        for category in LeisureCategory
        for gender in ("male", "female")
    }


def test_build_leisure_cites_a_source_for_every_row() -> None:
    for row in build_leisure(Locale.DE, fetch=fake_fetch).rows:
        assert "tus_20age" in row.source
        assert all(code in row.source for code in _EUROSTAT_CODES[row.category])


def test_write_leisure_round_trips_through_the_committed_csv(tmp_path) -> None:
    result = build_leisure(Locale.DE, fetch=fake_fetch)

    write_leisure(result, tmp_path)

    with (tmp_path / "de.csv").open(newline="") as f:
        written = list(csv.DictReader(f))
    assert len(written) == len(result.rows)
    assert set(written[0]) == {
        "category",
        "gender",
        "participation_rate",
        "participant_minutes",
        "source",
    }
    games_male = next(
        r for r in written if r["category"] == "games" and r["gender"] == "male"
    )
    assert float(games_male["participation_rate"]) == pytest.approx(0.1678, abs=1e-4)
