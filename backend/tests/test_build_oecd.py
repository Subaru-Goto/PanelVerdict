import pytest

from app.schemas import EducationLevel
from pipeline.build_oecd import _isced_to_education, _sex_to_gender


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
