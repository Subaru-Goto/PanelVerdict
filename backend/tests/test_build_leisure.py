import csv
import json
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.schemas import LeisureCategory, Locale
from pipeline.build_leisure import (
    _ESTAT_ACTIVITIES,
    _EUROSTAT_CODES,
    LeisureBuildResult,
    LeisureRow,
    _hhmm_to_minutes,
    build_leisure,
    parse_estat_table,
    parse_jsonstat,
    write_leisure,
)

_FIXTURES = Path(__file__).parent / "fixtures"

_TV_JP = "Watching TV, listening to the radio, reading newspapers or magazines"


def de_fetch(url: str) -> bytes:
    assert "tus_20age" in url and "geo=DE" in url
    return (_FIXTURES / "eurostat_tus_deu.json").read_bytes()


def jp_fetch(url: str) -> bytes:
    assert "e-stat.go.jp" in url
    return (_FIXTURES / "estat_shakai_seikatsu_2021_table1_1.xlsx").read_bytes()


def _rows_by_key(
    result: LeisureBuildResult,
) -> dict[tuple[LeisureCategory, str], LeisureRow]:
    return {(row.category, row.gender): row for row in result.rows}


def test_hhmm_to_minutes_parses_published_time_strings() -> None:
    assert _hhmm_to_minutes("2:07") == 127
    assert _hhmm_to_minutes("0:06") == 6


def test_parse_jsonstat_separates_the_three_published_units() -> None:
    cells = parse_jsonstat(de_fetch("tus_20age?geo=DE").decode())

    # published values, read straight off the Eurostat table
    assert cells.minutes[("male", "AC821")] == 132  # 2:12
    assert cells.participant_minutes[("male", "AC821")] == 180  # 3:00
    assert cells.rates[("male", "AC821")] == pytest.approx(0.7325)
    assert cells.rates[("female", "AC812")] == pytest.approx(0.1798)


def test_build_leisure_uses_the_published_participant_time_when_it_can() -> None:
    # GAMES maps to AC733-735 alone, so Eurostat's own participation time
    # (2:38 = 158 min at a 16.78% rate) is exact — deriving minutes/rate here
    # would drift by ~3 minutes for no reason.
    row = _rows_by_key(build_leisure(Locale.DE, fetch=de_fetch))[
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
    row = _rows_by_key(build_leisure(Locale.DE, fetch=de_fetch))[
        (LeisureCategory.TV_MEDIA, "male")
    ]

    assert row.participation_rate == pytest.approx(0.7602, abs=1e-4)
    assert row.participant_minutes == pytest.approx(182.8, abs=0.1)


def test_build_leisure_declares_which_categories_were_derived() -> None:
    result = build_leisure(Locale.DE, fetch=de_fetch)

    declared = " ".join(result.imputations)
    assert "independence" in declared.lower()
    # single-code categories are published exactly, so only the aggregated ones
    # may appear in the declaration
    for category, codes in _EUROSTAT_CODES.items():
        assert (category.value in declared) is (len(codes) > 1)


def test_walking_stays_its_own_category_since_it_is_published_separately() -> None:
    # AC611 is published apart from AC6_X_611, and walking is the single most
    # common activity in the Japanese survey — folding it into sports would
    # discard the distinction before the sampler ever sees it.
    row = _rows_by_key(build_leisure(Locale.DE, fetch=de_fetch))[
        (LeisureCategory.OUTDOOR_WALKING, "male")
    ]

    assert row.participation_rate == pytest.approx(0.1492, abs=1e-4)
    assert row.participant_minutes == pytest.approx(99.0, abs=0.1)  # 1:39


def test_build_leisure_cites_a_source_for_every_row() -> None:
    for row in build_leisure(Locale.DE, fetch=de_fetch).rows:
        assert "tus_20age" in row.source
        assert all(code in row.source for code in _EUROSTAT_CODES[row.category])


def test_parse_estat_table_reads_each_metric_from_its_own_block() -> None:
    # The published sheet lays population minutes, participant minutes and
    # participation rate side by side over one repeated set of activity headers.
    # Reading the wrong block would swap a percentage for a duration, so pin one
    # activity's three values: men's Sports is 16 / 121 min / 13.2%.
    cells = parse_estat_table(jp_fetch("e-stat.go.jp"))

    assert cells.minutes[("male", "Sports")] == 16
    assert cells.participant_minutes[("male", "Sports")] == 121
    assert cells.rates[("male", "Sports")] == pytest.approx(0.132)
    # and the other gender's block is a separate row, not the same one reread
    assert cells.rates[("female", "Sports")] == pytest.approx(0.106)


def test_parse_estat_table_cross_checks_against_the_published_ratio() -> None:
    # 行動者平均時間 is published, so it never has to be derived — but it should
    # agree with 総平均時間 / 行動者率: 131 / 0.542 = 241.7 against a published 242.
    cells = parse_estat_table(jp_fetch("e-stat.go.jp"))

    derived = cells.minutes[("male", _TV_JP)] / cells.rates[("male", _TV_JP)]
    assert derived == pytest.approx(
        cells.participant_minutes[("male", _TV_JP)], abs=1.0
    )


def test_parse_estat_table_rejects_a_sheet_whose_metric_blocks_are_missing() -> None:
    # The block labels are what tell minutes apart from percentages. If e-Stat
    # ever reshapes the sheet, this must fail loudly rather than read column 26
    # of whatever happens to be there.
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet["A1"] = "総平均時間 (分)"  # only one of the three blocks
    sheet["B2"] = "Sports"
    payload = BytesIO()
    workbook.save(payload)

    with pytest.raises(ValueError, match="metric-block"):
        parse_estat_table(payload.getvalue())


def test_build_leisure_japan_reads_every_category_from_a_published_cell() -> None:
    # Each Japanese category maps to exactly one diary activity, so nothing is
    # aggregated and nothing needs the independence union Germany needs.
    result = build_leisure(Locale.JP, fetch=jp_fetch)
    rows = _rows_by_key(result)

    assert rows[(LeisureCategory.HOBBIES_AMUSEMENTS, "male")].participation_rate == (
        pytest.approx(0.274)
    )
    assert rows[(LeisureCategory.HOBBIES_AMUSEMENTS, "male")].participant_minutes == (
        pytest.approx(214.0)
    )
    assert rows[(LeisureCategory.TV_MEDIA, "female")].participation_rate == (
        pytest.approx(0.594)
    )
    assert "independence" not in " ".join(result.imputations).lower()


def test_build_leisure_japan_cites_the_table_and_activity_for_every_row() -> None:
    for row in build_leisure(Locale.JP, fetch=jp_fetch).rows:
        assert "shakai-seikatsu-2021" in row.source
        assert all(name in row.source for name in _ESTAT_ACTIVITIES[row.category])


def test_build_leisure_japan_declares_what_its_taxonomy_cannot_separate() -> None:
    # Japan's diary has one "Hobbies and amusements" bucket where Eurostat
    # publishes games, reading, computer use, arts and gardening separately.
    # Those categories are absent rather than guessed at, and each says why.
    result = build_leisure(Locale.JP, fetch=jp_fetch)

    unsupported = {entry.category: entry.reason for entry in result.unsupported}
    assert LeisureCategory.GAMES in unsupported
    assert LeisureCategory.READING in unsupported
    assert LeisureCategory.COMPUTER_LEISURE in unsupported
    assert LeisureCategory.GARDENING_PETS in unsupported
    assert LeisureCategory.ARTS_HOBBIES in unsupported
    assert LeisureCategory.OUTDOOR_WALKING in unsupported
    assert all(reason.strip() for reason in unsupported.values())


def test_rest_relaxation_is_filled_from_both_surveys() -> None:
    # Eurostat publishes resting inside its AC4-8 leisure aggregate (AC531), not
    # under personal care, so Japan's 休養・くつろぎ has a counterpart and neither
    # country has to declare the category missing. The two are ~4x apart on scope,
    # which jp.meta.json declares rather than smooths over.
    de = _rows_by_key(build_leisure(Locale.DE, fetch=de_fetch))
    jp = _rows_by_key(build_leisure(Locale.JP, fetch=jp_fetch))

    de_male = de[(LeisureCategory.REST_RELAXATION, "male")]
    assert de_male.participation_rate == pytest.approx(0.1845, abs=1e-4)
    assert de_male.participant_minutes == pytest.approx(59.0)

    jp_male = jp[(LeisureCategory.REST_RELAXATION, "male")]
    assert jp_male.participation_rate == pytest.approx(0.681)
    assert jp_male.participant_minutes == pytest.approx(175.0)


def test_build_leisure_germany_declares_the_japan_only_coarse_bucket() -> None:
    # The enum is a union across surveys, so Germany has to account for the
    # category only Japan's coarser taxonomy produces.
    result = build_leisure(Locale.DE, fetch=de_fetch)

    unsupported = {entry.category for entry in result.unsupported}
    assert unsupported == {LeisureCategory.HOBBIES_AMUSEMENTS}


@pytest.mark.parametrize(
    ("country", "fetch"),
    [(Locale.DE, de_fetch), (Locale.JP, jp_fetch)],
)
def test_every_country_accounts_for_every_category(
    country: Locale, fetch: Callable[[str], bytes]
) -> None:
    # The invariant that makes a union vocabulary honest: a category is either
    # filled from a published cell or explicitly declared unavailable. Adding an
    # enum member without touching a country's mapping must fail, not default.
    result = build_leisure(country, fetch=fetch)

    filled = {row.category for row in result.rows}
    declared = {entry.category for entry in result.unsupported}
    assert filled | declared == set(LeisureCategory)
    assert not filled & declared
    assert len(result.rows) == len(filled) * 2


def test_build_leisure_us_points_at_its_own_slice() -> None:
    with pytest.raises(NotImplementedError, match="ATUS"):
        build_leisure(Locale.US, fetch=de_fetch)


def test_write_leisure_round_trips_through_the_committed_csv(tmp_path) -> None:
    result = build_leisure(Locale.DE, fetch=de_fetch)

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
    result = build_leisure(Locale.DE, fetch=de_fetch)

    write_leisure(result, tmp_path)

    meta = json.loads((tmp_path / "de.meta.json").read_text())
    assert meta["imputations"] == result.imputations
    assert meta["country"] == "DE"


def test_write_leisure_commits_the_missing_categories_too(tmp_path) -> None:
    # coverage is the whole point of a union vocabulary: a reader of jp.csv must
    # be able to tell "no games row" from "Japan publishes no games figure"
    result = build_leisure(Locale.JP, fetch=jp_fetch)

    write_leisure(result, tmp_path)

    meta = json.loads((tmp_path / "jp.meta.json").read_text())
    assert {entry["category"] for entry in meta["unsupported"]} == {
        entry.category.value for entry in result.unsupported
    }
    assert all(entry["reason"] for entry in meta["unsupported"])
