import pytest

from app.schemas import EducationLevel
from pipeline.build_oecd import (
    _dl_band_for_5yr,
    _edu_band_for_5yr,
    _INCOME_SPLIT,
    _isced_to_education,
    _sex_to_gender,
    attach_income,
    combine,
)


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


def test_income_splits_are_valid_distributions():
    for split in _INCOME_SPLIT.values():
        assert len(split) == 5
        assert sum(split) == pytest.approx(1.0)
