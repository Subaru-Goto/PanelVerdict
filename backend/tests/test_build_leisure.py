import csv
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.schemas import LeisureCategory, Locale
from pipeline.build_leisure import (
    _AGE_BANDS,
    _EUROSTAT_AGE,
    SurveyCells,
    _cell_rate,
    _leisure_rows,
    build_leisure,
    parse_estat_table,
    parse_jsonstat,
    write_leisure,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def de_fetch(url: str) -> bytes:
    assert "tus_20age" in url and "geo=DE" in url
    return (_FIXTURES / "eurostat_tus_deu_by_age.json").read_bytes()


def jp_fetch(url: str) -> bytes:
    assert "e-stat.go.jp" in url
    return (_FIXTURES / "estat_shakai_seikatsu_2021_table1_1.xlsx").read_bytes()


def _rates(
    country: Locale, fetch: Callable[[str], bytes]
) -> dict[tuple[LeisureCategory, str, str], float]:
    return {
        (row.category, row.gender, row.age_band): row.participation_rate
        for row in build_leisure(country, fetch=fetch).rows
    }


def test_parse_jsonstat_reads_rates_by_gender_and_age() -> None:
    cells = parse_jsonstat(de_fetch("tus_20age?geo=DE").decode())

    # published Eurostat cells, read straight off the table
    assert cells.rates[("male", "Y15-24", "AC733-735")] == pytest.approx(0.3621)
    assert cells.rates[("female", "Y_GE65", "AC821")] == pytest.approx(0.8687)
    # the survey's own totals are kept, since they are the fallback prior
    assert cells.totals == ("total", "TOTAL")
    assert ("total", "TOTAL", "AC4") in cells.rates


def test_parse_estat_table_reads_rates_by_gender_and_age() -> None:
    cells = parse_estat_table(jp_fetch("e-stat.go.jp"))

    # 男 / 25～29歳 / 趣味・娯楽 is published as 36.5%, with the age group's own
    # population beside it — the weight the two middle bands are combined on
    assert cells.rates[("male", "25~29歳", "Hobbies and amusements")] == (
        pytest.approx(0.365)
    )
    assert cells.populations[("male", "25~29歳")] == pytest.approx(3244.0)
    assert cells.totals == ("total", "")


def test_estat_age_labels_survive_furigana_and_a_fullwidth_tilde() -> None:
    # the sheet writes "15～24歳サイ": a fullwidth tilde plus trailing furigana
    cells = parse_estat_table(jp_fetch("e-stat.go.jp"))

    assert ("male", "15~24歳", "Sports") in cells.rates
    assert ("female", "65歳以上", "Sports") in cells.rates


def test_build_leisure_covers_every_category_gender_and_band() -> None:
    for country, fetch in ((Locale.DE, de_fetch), (Locale.JP, jp_fetch)):
        rates = _rates(country, fetch)
        assert set(rates) == {
            (category, gender, band)
            for category in LeisureCategory
            for gender in ("male", "female")
            for band in _AGE_BANDS
        }


def test_a_category_spanning_several_codes_is_the_independence_union() -> None:
    # tv_media is AC821 + AC831 + AC81_X_812 for Germany, and one person is
    # counted under each, so the rates cannot be added — the union is
    # 1 - prod(1-r), which must exceed every part and stay under their sum.
    cells = parse_jsonstat(de_fetch("tus_20age?geo=DE").decode())
    parts = [
        cells.rates[("male", "Y25-34", code)]
        for code in ("AC821", "AC831", "AC81_X_812")
    ]
    expected = 1.0
    for part in parts:
        expected *= 1 - part

    row = _rates(Locale.DE, de_fetch)[(LeisureCategory.TV_MEDIA, "male", "25-34")]

    assert row == pytest.approx(1 - expected)
    assert max(parts) < row < sum(parts)


def test_japan_combines_its_five_year_groups_by_population() -> None:
    # 25-34 is not published ready-made: 25～29歳 is 36.5% over 3244 thousand men
    # and 30～34歳 is 29.1% over 3324, so the band is the population-weighted
    # mean (.365*3244 + .291*3324) / 6568 = 0.3275 — not the plain average.
    row = _rates(Locale.JP, jp_fetch)[
        (LeisureCategory.HOBBIES_AND_GAMES, "male", "25-34")
    ]

    assert row == pytest.approx(0.3275, abs=1e-4)
    assert row != pytest.approx((0.365 + 0.291) / 2, abs=1e-4)


def test_bands_published_ready_made_are_read_not_combined() -> None:
    # 45～54歳 is published as one group, so it is taken as-is
    cells = parse_estat_table(jp_fetch("e-stat.go.jp"))
    published = cells.rates[("male", "45~54歳", "Hobbies and amusements")]

    row = _rates(Locale.JP, jp_fetch)[
        (LeisureCategory.HOBBIES_AND_GAMES, "male", "45-54")
    ]

    assert row == pytest.approx(published)


def test_age_conditioning_produces_a_real_gradient() -> None:
    # the reason for conditioning at all: if every band came out the same, the
    # extra column would be costing complexity and buying nothing
    rates = _rates(Locale.JP, jp_fetch)
    by_band = [rates[(LeisureCategory.TV_MEDIA, "male", b)] for b in _AGE_BANDS]

    assert by_band == sorted(by_band)  # TV rises monotonically with age in Japan
    assert max(by_band) - min(by_band) > 0.3


def test_a_missing_cell_falls_back_to_the_coarsest_published_prior() -> None:
    # ATUS publishes participation by sex but not by age. Rather than drop such a
    # country, the gender's own all-ages figure stands in for every band.
    cells = SurveyCells(
        rates={("male", "TOTAL", "reading"): 0.4, ("total", "TOTAL", "reading"): 0.35},
        populations={},
        totals=("total", "TOTAL"),
    )

    assert _cell_rate(cells, "male", "Y25-34", "reading") == (0.4, "gender only")
    # and with no gendered figure either, the national total is the last resort
    assert _cell_rate(cells, "female", "Y25-34", "reading") == (0.35, "neither")


def test_the_finest_published_cell_wins_over_its_priors() -> None:
    cells = SurveyCells(
        rates={
            ("male", "Y25-34", "reading"): 0.5,
            ("male", "TOTAL", "reading"): 0.4,
            ("total", "TOTAL", "reading"): 0.35,
        },
        populations={},
        totals=("total", "TOTAL"),
    )

    assert _cell_rate(cells, "male", "Y25-34", "reading") == (0.5, "gender and age")


def test_a_cell_with_no_prior_at_any_level_is_an_error() -> None:
    cells = SurveyCells(rates={}, populations={}, totals=("total", "TOTAL"))

    with pytest.raises(KeyError, match="no published rate"):
        _cell_rate(cells, "male", "Y25-34", "reading")


def test_countries_conditioned_on_both_axes_declare_no_fallback() -> None:
    # Germany and Japan both publish activity by gender and age, so nothing
    # should be standing in for anything — a fallback note here would mean a
    # mapping typo silently resolved to a coarser number.
    for country, fetch in ((Locale.DE, de_fetch), (Locale.JP, jp_fetch)):
        declared = " ".join(build_leisure(country, fetch=fetch).imputations)
        assert "not conditioned on both gender and age" not in declared


def test_a_category_missing_from_a_mapping_fails_the_build() -> None:
    # Iterating the mapping would emit a short table instead of complaining, so
    # adding an enum member without mapping it has to be a build failure.
    cells = SurveyCells(rates={}, populations={}, totals=("total", "TOTAL"))
    partial = {LeisureCategory.TV_MEDIA: ("AC821",)}

    with pytest.raises(ValueError, match="no activities mapped"):
        _leisure_rows(cells, partial, _EUROSTAT_AGE, "test")


def test_published_activities_left_unmapped_are_declared() -> None:
    # A reader must be able to tell "we decided against this" from "we forgot".
    # Eurostat's resting and gardening, and Japan's 休養・くつろぎ, are all
    # published inside the leisure block and deliberately excluded.
    declared_de = " ".join(build_leisure(Locale.DE, fetch=de_fetch).imputations)
    for code in ("AC531", "AC221", "AC34"):
        assert code in declared_de
    # and the mapped-but-narrower cases say so too
    assert "handicraft" in declared_de and "recordings" in declared_de

    declared_jp = " ".join(build_leisure(Locale.JP, fetch=jp_fetch).imputations)
    assert "休養・くつろぎ" in declared_jp


def test_build_leisure_cites_a_source_for_every_row() -> None:
    for country, fetch, dataset in (
        (Locale.DE, de_fetch, "tus_20age"),
        (Locale.JP, jp_fetch, "shakai-seikatsu-2021"),
    ):
        for row in build_leisure(country, fetch=fetch).rows:
            assert dataset in row.source


def test_the_us_falls_back_to_its_gender_only_prior_for_every_band() -> None:
    # ATUS publishes activity by sex but not by age, so the six bands must all
    # carry the same rate — and the table must say so rather than look
    # age-conditioned. This is the fallback ladder doing its job end to end.
    rates = _rates(Locale.US, de_fetch)
    by_band = {
        band: rates[(LeisureCategory.TV_MEDIA, "male", band)] for band in _AGE_BANDS
    }

    assert len(set(by_band.values())) == 1  # one prior stretched over every band
    assert by_band["15-24"] == pytest.approx(0.757)  # the published male figure
    declared = " ".join(build_leisure(Locale.US, fetch=de_fetch).imputations)
    assert "not conditioned on both gender and age" in declared
    assert "gender only" in declared


def test_us_hobbies_unions_the_four_rows_atus_publishes_separately() -> None:
    # ATUS splits what Japan bundles: playing games 18.5%, computer use 14.5%,
    # reading 13.4% and arts 1.9% for men. Union under independence:
    # 1 - .815*.855*.866*.981 = 0.4080 — not the 48.3% those rates sum to.
    row = _rates(Locale.US, de_fetch)[
        (LeisureCategory.HOBBIES_AND_GAMES, "male", "35-44")
    ]

    assert row == pytest.approx(0.4080, abs=1e-4)
    assert row < 0.185 + 0.145 + 0.134 + 0.019


def test_write_leisure_round_trips_through_the_committed_csv(tmp_path) -> None:
    result = build_leisure(Locale.JP, fetch=jp_fetch)

    write_leisure(result, tmp_path)

    with (tmp_path / "jp.csv").open(newline="") as f:
        written = list(csv.DictReader(f))
    assert len(written) == len(result.rows)
    assert set(written[0]) == {
        "category",
        "gender",
        "age_band",
        "participation_rate",
        "source",
    }
    row = next(
        r
        for r in written
        if r["category"] == "hobbies_and_games"
        and r["gender"] == "male"
        and r["age_band"] == "25-34"
    )
    assert float(row["participation_rate"]) == pytest.approx(0.3275, abs=1e-4)


def test_write_leisure_commits_the_imputations_beside_the_csv(tmp_path) -> None:
    # a caveat that only reaches stdout is a caveat nobody reading the committed
    # data will ever see (build_oecd's write_joint sets this precedent)
    result = build_leisure(Locale.JP, fetch=jp_fetch)

    write_leisure(result, tmp_path)

    meta = json.loads((tmp_path / "jp.meta.json").read_text())
    assert meta["imputations"] == result.imputations
    assert meta["country"] == "JP"
