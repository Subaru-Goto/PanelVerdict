import json
from pathlib import Path

import pytest

import app.sampler as sampler
from app.sampler import JointCell, load_joint
from app.schemas import EducationLevel, Locale
from pipeline.build_oecd import (
    _complete_education_from_peers,
    _dl_band_for_5yr,
    _edu_band_for_5yr,
    _education_is_incomplete,
    _INCOME_SPLIT,
    _rake_income,
    _isced_to_education,
    _ref_area,
    _sex_to_gender,
    attach_income,
    build_oecd,
    BuildResult,
    combine,
    parse_sdmx_csv,
    write_joint,
)

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("code", "level"),
    [
        ("ISCED11A_0T2", EducationLevel.BELOW_SECONDARY),
        ("ISCED11A_3_4", EducationLevel.SECONDARY),
        ("ISCED11A_5T8", EducationLevel.TERTIARY),
    ],
)
def test_isced_to_education(code, level):
    assert _isced_to_education(code) == level


@pytest.mark.parametrize(("code", "gender"), [("F", "female"), ("M", "male")])
def test_sex_to_gender(code, gender):
    assert _sex_to_gender(code) == gender


@pytest.mark.parametrize(
    ("group", "band"),
    [
        ("Y15T19", "18-19"),
        ("Y20T24", "20-29"),
        ("Y25T29", "20-29"),
        ("Y30T34", "30-39"),
        ("Y35T39", "30-39"),
        ("Y60T64", "60-69"),
        ("Y65T69", "60-69"),
        ("Y80T84", "80+"),
        ("Y_GE85", "80+"),
    ],
)
def test_dl_band_for_5yr(group, band):
    assert _dl_band_for_5yr(group) == band


@pytest.mark.parametrize(
    ("group", "edu_band"),
    [
        ("Y15T19", "Y25T34"),  # <25: borrow youngest observed (imputed)
        ("Y20T24", "Y25T34"),  # <25: borrow youngest observed (imputed)
        ("Y25T29", "Y25T34"),
        ("Y30T34", "Y25T34"),
        ("Y35T39", "Y35T44"),
        ("Y45T49", "Y45T54"),
        ("Y55T59", "Y55T64"),
        ("Y60T64", "Y55T64"),
        ("Y65T69", "Y55T64"),  # >=65: borrow oldest observed (imputed)
        ("Y_GE85", "Y55T64"),  # >=65: borrow oldest observed (imputed)
    ],
)
def test_edu_band_for_5yr(group, edu_band):
    assert _edu_band_for_5yr(group) == edu_band


def test_combine_blends_edu_bands_within_a_dl_band():
    # Y30T34 and Y35T39 both roll up to "30-39" but draw education from
    # different bands (Y25T34 vs Y35T44) — so the band's mix is the
    # population-weighted blend of the two.
    population = {("Y30T34", "F"): 100.0, ("Y35T39", "F"): 300.0}
    education = {
        ("Y25T34", "F", "ISCED11A_5T8"): 0.5,
        ("Y25T34", "F", "ISCED11A_3_4"): 0.5,
        ("Y35T44", "F", "ISCED11A_5T8"): 0.3,
        ("Y35T44", "F", "ISCED11A_3_4"): 0.7,
    }
    joint = combine(population, education)
    # tertiary: 100*0.5 + 300*0.3 = 140 ; secondary: 100*0.5 + 300*0.7 = 260
    assert joint[("30-39", "female", EducationLevel.TERTIARY)] == pytest.approx(140.0)
    assert joint[("30-39", "female", EducationLevel.SECONDARY)] == pytest.approx(260.0)
    assert sum(joint.values()) == pytest.approx(400.0)


def test_combine_applies_floor_fraction_to_youngest_group():
    # Y15T19 spans 15-19, but only 18-19 clears the age floor: 2 of 5 years.
    population = {("Y15T19", "M"): 500.0}
    education = {("Y25T34", "M", "ISCED11A_3_4"): 1.0}
    joint = combine(population, education)
    # 500 * (2/5) * 1.0 = 200; the 15-17 portion is dropped.
    assert joint[("18-19", "male", EducationLevel.SECONDARY)] == pytest.approx(200.0)
    assert sum(joint.values()) == pytest.approx(200.0)


def test_attach_income_splits_each_cell_into_five_quintiles_conserving_mass():
    combined = {("30-39", "female", EducationLevel.TERTIARY): 100.0}
    joint = attach_income(combined)
    assert sorted(q for (*_, q) in joint) == [1, 2, 3, 4, 5]
    assert sum(joint.values()) == pytest.approx(100.0)


def test_attach_income_skews_with_education():
    combined = {
        ("40-49", "male", EducationLevel.TERTIARY): 100.0,
        ("40-49", "male", EducationLevel.BELOW_SECONDARY): 100.0,
    }
    joint = attach_income(combined)
    top, bottom = EducationLevel.TERTIARY, EducationLevel.BELOW_SECONDARY
    # tertiary is top-heavy, below-secondary bottom-heavy — the coherence the
    # off-diagonal argument needs, and no row collapses onto a single quintile.
    assert joint[("40-49", "male", top, 5)] > joint[("40-49", "male", top, 1)]
    assert joint[("40-49", "male", bottom, 1)] > joint[("40-49", "male", bottom, 5)]


def _skewed_joint() -> dict[tuple[str, str, EducationLevel, int], float]:
    # two cells of 100 each whose splits skew opposite ways, so the raw quintile
    # marginal is non-uniform (q1=43 ... q5=35) — something to rake.
    tertiary = [8.0, 14.0, 20.0, 28.0, 30.0]
    below = [35.0, 28.0, 20.0, 12.0, 5.0]
    joint: dict[tuple[str, str, EducationLevel, int], float] = {}
    for q in range(1, 6):
        joint[("30-39", "male", EducationLevel.TERTIARY, q)] = tertiary[q - 1]
        joint[("30-39", "male", EducationLevel.BELOW_SECONDARY, q)] = below[q - 1]
    return joint


def test_rake_income_makes_quintiles_uniform():
    raked = _rake_income(_skewed_joint())
    total = sum(raked.values())
    for q in range(1, 6):
        share = sum(w for (*_, qq), w in raked.items() if qq == q) / total
        assert share == pytest.approx(0.20, abs=1e-6)


def test_rake_income_preserves_cell_totals():
    joint = _skewed_joint()
    raked = _rake_income(joint)
    for edu in (EducationLevel.TERTIARY, EducationLevel.BELOW_SECONDARY):
        before = sum(w for (_, _, e, _), w in joint.items() if e == edu)
        after = sum(w for (_, _, e, _), w in raked.items() if e == edu)
        assert after == pytest.approx(before)  # real demographics must not move


def test_rake_income_preserves_education_income_association():
    raked = _rake_income(_skewed_joint())
    ter = {q: raked[("30-39", "male", EducationLevel.TERTIARY, q)] for q in range(1, 6)}
    low = {q: raked[("30-39", "male", EducationLevel.BELOW_SECONDARY, q)] for q in range(1, 6)}
    assert ter[5] > ter[1]  # tertiary still skews high after raking
    assert low[1] > low[5]  # below-secondary still skews low


def test_income_splits_are_valid_distributions():
    for split in _INCOME_SPLIT.values():
        assert len(split) == 5
        assert sum(split) == pytest.approx(1.0)


def test_parse_sdmx_csv_keys_population_by_age_and_sex():
    text = (_FIXTURES / "oecd_population_usa.csv").read_text()
    pop = parse_sdmx_csv(text, ("AGE", "SEX"))
    assert pop[("Y40T44", "M")] == pytest.approx(10967569.0)
    assert len(pop) == 30  # 15 five-year groups x 2 sexes


def test_parse_sdmx_csv_keys_education_by_age_sex_attainment():
    text = (_FIXTURES / "oecd_education_usa.csv").read_text()
    edu = parse_sdmx_csv(text, ("AGE", "SEX", "ATTAINMENT_LEV"))
    assert edu[("Y25T34", "F", "ISCED11A_5T8")] == pytest.approx(57.22052002)
    assert len(edu) == 24  # 4 age bands x 2 sexes x 3 attainment levels


def test_parse_sdmx_csv_skips_rows_with_no_observation():
    # JP reports only tertiary in this dataflow; the below/secondary rows come
    # back with an empty OBS_VALUE (no observation, not malformed) — skip them.
    text = (_FIXTURES / "oecd_education_jpn.csv").read_text()
    edu = parse_sdmx_csv(text, ("AGE", "SEX", "ATTAINMENT_LEV"))
    assert len(edu) == 8  # 4 age bands x 2 sexes, tertiary only
    assert all(isced == "ISCED11A_5T8" for (_, _, isced) in edu)


@pytest.mark.parametrize(
    ("country", "code"),
    [(Locale.US, "USA"), (Locale.JP, "JPN"), (Locale.DE, "DEU")],
)
def test_ref_area(country, code):
    assert _ref_area(country) == code


def test_education_is_incomplete():
    tertiary_only = {("Y25T34", "M", "ISCED11A_5T8"): 0.6}
    missing_below = {
        ("Y25T34", "M", "ISCED11A_3_4"): 0.4,
        ("Y25T34", "M", "ISCED11A_5T8"): 0.6,
    }
    complete = {
        ("Y25T34", "M", "ISCED11A_0T2"): 0.1,
        ("Y25T34", "M", "ISCED11A_3_4"): 0.3,
        ("Y25T34", "M", "ISCED11A_5T8"): 0.6,
    }
    assert _education_is_incomplete(tertiary_only) is True
    assert _education_is_incomplete(missing_below) is True  # any gap shape, not just JP's
    assert _education_is_incomplete(complete) is False


def test_complete_education_from_peers():
    cell = ("Y25T34", "M")
    peers = [
        {(*cell, "ISCED11A_0T2"): 0.10, (*cell, "ISCED11A_3_4"): 0.40, (*cell, "ISCED11A_5T8"): 0.50},
        {(*cell, "ISCED11A_0T2"): 0.20, (*cell, "ISCED11A_3_4"): 0.40, (*cell, "ISCED11A_5T8"): 0.40},
    ]
    target = {(*cell, "ISCED11A_5T8"): 0.60}
    filled = _complete_education_from_peers(target, peers)
    # peer mean shares of the missing levels: below 0.15, secondary 0.40 (sum .55)
    # missing mass 0.40 splits proportionally: below .40*.15/.55, secondary .40*.40/.55
    assert filled[(*cell, "ISCED11A_5T8")] == pytest.approx(0.60)  # reported level exact
    assert filled[(*cell, "ISCED11A_0T2")] == pytest.approx(0.40 * 0.15 / 0.55)
    assert filled[(*cell, "ISCED11A_3_4")] == pytest.approx(0.40 * 0.40 / 0.55)
    assert sum(filled.values()) == pytest.approx(1.0)


def test_complete_education_from_peers_fills_only_the_missing_level():
    cell = ("Y35T44", "F")
    peers = [
        {(*cell, "ISCED11A_0T2"): 0.10, (*cell, "ISCED11A_3_4"): 0.30, (*cell, "ISCED11A_5T8"): 0.60},
    ]
    # reports secondary + tertiary, only below-secondary missing
    target = {(*cell, "ISCED11A_3_4"): 0.30, (*cell, "ISCED11A_5T8"): 0.55}
    filled = _complete_education_from_peers(target, peers)
    assert filled[(*cell, "ISCED11A_3_4")] == pytest.approx(0.30)  # untouched
    assert filled[(*cell, "ISCED11A_5T8")] == pytest.approx(0.55)  # untouched
    assert filled[(*cell, "ISCED11A_0T2")] == pytest.approx(0.15)  # 1 - .30 - .55


def test_complete_education_from_peers_fails_loud_on_incomplete_peer():
    cell = ("Y25T34", "M")
    target = {(*cell, "ISCED11A_5T8"): 0.60}  # needs below + secondary
    bad_peer = {(*cell, "ISCED11A_0T2"): 0.10, (*cell, "ISCED11A_5T8"): 0.50}  # no secondary
    with pytest.raises(ValueError, match="peer"):
        _complete_education_from_peers(target, [bad_peer])


def test_build_oecd_wires_fixtures_into_joint_rows():
    pop_text = (_FIXTURES / "oecd_population_usa.csv").read_text()
    edu_text = (_FIXTURES / "oecd_education_usa.csv").read_text()

    def fake_fetch(url: str) -> str:
        return pop_text if "DF_POP_HIST" in url else edu_text

    result = build_oecd(Locale.US, fetch=fake_fetch)

    assert result.country is Locale.US
    assert {c.income_quintile for c in result.rows} == {1, 2, 3, 4, 5}
    assert {c.gender for c in result.rows} == {"male", "female"}

    # End-to-end reconciliation: both 80+ groups (Y80T84, Y_GE85, female) roll
    # into "80+" and, being >=65, borrow the Y55T64 education mix. Summing over
    # quintiles undoes the income split, so this checks parse+combine alone.
    mass = sum(
        c.weight
        for c in result.rows
        if c.age_band == "80+"
        and c.gender == "female"
        and c.education is EducationLevel.TERTIARY
    )
    expected = (4520502 + 4374285) * (46.78384781 / 100)
    assert mass == pytest.approx(expected)

    assert len(result.income_marginal) == 5
    assert sum(result.income_marginal) == pytest.approx(1.0)


def test_build_oecd_borrows_jp_split_from_peers():
    fx = {
        "jp_pop": (_FIXTURES / "oecd_population_jpn.csv").read_text(),
        "jp_edu": (_FIXTURES / "oecd_education_jpn.csv").read_text(),
        "us_edu": (_FIXTURES / "oecd_education_usa.csv").read_text(),
        "de_edu": (_FIXTURES / "oecd_education_deu.csv").read_text(),
    }

    def fake_fetch(url: str) -> str:
        if "DF_POP_HIST" in url:
            return fx["jp_pop"]
        if "USA" in url:
            return fx["us_edu"]
        if "DEU" in url:
            return fx["de_edu"]
        return fx["jp_edu"]

    result = build_oecd(Locale.JP, fetch=fake_fetch)

    # JP reports only tertiary; the peer borrow must fill below-secondary + secondary
    assert {c.education for c in result.rows} == {
        EducationLevel.BELOW_SECONDARY,
        EducationLevel.SECONDARY,
        EducationLevel.TERTIARY,
    }
    assert any(
        "peers" in note and "US" in note and "DE" in note
        for note in result.imputations
    )


def test_write_joint_round_trips_through_load_joint(tmp_path, monkeypatch):
    monkeypatch.setattr(sampler, "_JOINT_DIR", tmp_path)
    result = BuildResult(
        country=Locale.US,
        rows=[
            JointCell(
                age_band="20-29",
                gender="female",
                education=EducationLevel.TERTIARY,
                income_quintile=3,
                weight=12.5,
            )
        ],
        income_marginal=[0.2, 0.2, 0.2, 0.2, 0.2],
        imputations=["income conditioned on education only"],
    )
    write_joint(result, tmp_path)
    # the CSV the sampler will actually read must reconstruct the same cells
    assert load_joint(Locale.US) == result.rows
    meta = json.loads((tmp_path / "us.meta.json").read_text())
    assert meta["income_marginal"] == result.income_marginal
    assert meta["imputations"] == result.imputations
