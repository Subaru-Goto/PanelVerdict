import csv
import json
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


def test_parse_jsonstat_separates_the_three_published_units() -> None:
    cells = parse_jsonstat(fake_fetch("tus_20age?geo=DE"))

    # published values, read straight off the Eurostat table
    assert cells.minutes[("M", "AC821")] == 132  # 2:12
    assert cells.participant_minutes[("M", "AC821")] == 180  # 3:00
    assert cells.rates[("M", "AC821")] == pytest.approx(0.7325)
    assert cells.rates[("F", "AC812")] == pytest.approx(0.1798)


def test_build_leisure_uses_the_published_participant_time_when_it_can() -> None:
    # GAMES maps to AC733-735 alone, so Eurostat's own participation time
    # (2:38 = 158 min at a 16.78% rate) is exact — deriving minutes/rate here
    # would drift by ~3 minutes for no reason.
    row = _rows_by_key(build_leisure(Locale.DE, fetch=fake_fetch))[
        (LeisureCategory.GAMES, "male")
    ]

    assert row.participation_rate == pytest.approx(0.1678, abs=1e-4)
    assert row.participant_minutes == pytest.approx(158.0, abs=0.1)


def test_build_leisure_derives_only_for_aggregated_categories() -> None:
    # TV_MEDIA = AC821 (2:12, 73.25%) + AC831 (0:07, 10.36%) for males. There is
    # no published participation time for the union, so it must be derived:
    # minutes add (132 + 7 = 139) but rates cannot (participants overlap), so
    # the union under independence is 1 - (1-.7325)(1-.1036) = 0.7602, giving
    # 139 / 0.7602 = 182.8 — which cross-checks against AC821's published 3:00.
    row = _rows_by_key(build_leisure(Locale.DE, fetch=fake_fetch))[
        (LeisureCategory.TV_MEDIA, "male")
    ]

    assert row.participation_rate == pytest.approx(0.7602, abs=1e-4)
    assert row.participant_minutes == pytest.approx(182.8, abs=0.1)


def test_build_leisure_declares_which_categories_were_derived() -> None:
    result = build_leisure(Locale.DE, fetch=fake_fetch)

    declared = " ".join(result.imputations)
    assert "independence" in declared.lower()
    # single-code categories are published exactly, so only the aggregated ones
    # may appear in the declaration
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


def test_walking_stays_its_own_category_since_it_is_published_separately() -> None:
    # AC611 is published apart from AC6_X_611, and walking is the single most
    # common activity in the Japanese survey — folding it into sports would
    # discard the distinction before the sampler ever sees it.
    row = _rows_by_key(build_leisure(Locale.DE, fetch=fake_fetch))[
        (LeisureCategory.OUTDOOR_WALKING, "male")
    ]

    assert row.participation_rate == pytest.approx(0.1492, abs=1e-4)
    assert row.participant_minutes == pytest.approx(99.0, abs=0.1)  # 1:39


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


def test_write_leisure_commits_the_imputations_beside_the_csv(tmp_path) -> None:
    # a caveat that only reaches stdout is a caveat nobody reading the committed
    # data will ever see (build_oecd's write_joint sets this precedent)
    result = build_leisure(Locale.DE, fetch=fake_fetch)

    write_leisure(result, tmp_path)

    meta = json.loads((tmp_path / "de.meta.json").read_text())
    assert meta["imputations"] == result.imputations
    assert meta["country"] == "DE"
