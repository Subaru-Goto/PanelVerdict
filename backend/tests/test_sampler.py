import numpy as np
import pytest
from pydantic import ValidationError

from app.sampler import JointCell, _resolve_age, load_joint, sample_demographics
from app.schemas import EducationLevel, Locale, PersonaDemographics


@pytest.fixture
def joint_file(tmp_path, monkeypatch):
    (tmp_path / "us.csv").write_text(
        "age_band,gender,education,income_quintile,weight\n"
        "20-29,female,tertiary,4,0.5\n"
        "30-39,male,secondary,2,0.3\n"
        "80+,female,below_secondary,1,0.2\n"
    )
    monkeypatch.setattr("app.sampler._JOINT_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("band", "low", "high"),
    [("20-29", 20, 29), ("80+", 80, 100), ("18-19", 18, 19)],
)
def test_resolve_age_stays_within_band(band, low, high):
    rng = np.random.default_rng(0)
    ages = [_resolve_age(band, EducationLevel.SECONDARY, rng) for _ in range(50)]
    assert all(low <= age <= high for age in ages)


def test_resolve_age_tertiary_never_below_21():
    # "20-29" + tertiary would otherwise emit 20-year-old graduates
    rng = np.random.default_rng(0)
    ages = [_resolve_age("20-29", EducationLevel.TERTIARY, rng) for _ in range(200)]
    assert min(ages) >= 21
    assert max(ages) <= 29


def test_load_joint_parses_and_validates(joint_file):
    cells = load_joint(Locale.US)
    assert len(cells) == 3
    assert all(isinstance(c, JointCell) for c in cells)
    assert cells[0].age_band == "20-29"


def test_load_joint_rejects_a_malformed_row(tmp_path, monkeypatch):
    (tmp_path / "us.csv").write_text(
        "age_band,gender,education,income_quintile,weight\n"
        "20-29,female,tertiary,9,0.5\n"  # quintile 9 is out of range
    )
    monkeypatch.setattr("app.sampler._JOINT_DIR", tmp_path)
    with pytest.raises(ValidationError):
        load_joint(Locale.US)


def test_sample_is_deterministic_per_seed(joint_file):
    first = sample_demographics(Locale.US, 50, seed=7)
    assert first == sample_demographics(Locale.US, 50, seed=7)
    assert first != sample_demographics(Locale.US, 50, seed=8)


def test_sample_emits_valid_records_within_bands(joint_file):
    people = sample_demographics(Locale.US, 200, seed=1)
    assert len(people) == 200
    assert all(isinstance(p, PersonaDemographics) for p in people)
    assert all(p.country is Locale.US for p in people)
    for p in people:
        assert (20 <= p.age <= 29) or (30 <= p.age <= 39) or (80 <= p.age <= 100)


def test_sample_weights_bias_the_draw(joint_file):
    # the 20-29 cell has weight 0.5, so it should dominate over many draws
    people = sample_demographics(Locale.US, 1000, seed=2)
    twenties = sum(1 for p in people if 20 <= p.age <= 29)
    assert twenties > len(people) * 0.4
