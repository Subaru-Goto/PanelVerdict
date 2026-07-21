import pytest

pytest.importorskip("pandas")  # build_us is pipeline-group tooling

import pandas as pd  # noqa: E402

from app.schemas import Locale  # noqa: E402
from app.sampler import sample_demographics  # noqa: E402
from pipeline import build_us  # noqa: E402
from pipeline.build_us import (  # noqa: E402
    _age_band,
    _education_level,
    assign_income_quintile,
)


@pytest.mark.parametrize(
    ("age", "band"),
    [
        (18, "18-19"),
        (19, "18-19"),
        (20, "20-29"),
        (34, "30-39"),
        (79, "70-79"),
        (80, "80+"),
        (99, "80+"),
    ],
)
def test_age_band(age, band):
    assert _age_band(age) == band


@pytest.mark.parametrize(
    ("schl", "level"),
    [
        (1, "below_secondary"),
        (15, "below_secondary"),
        (16, "secondary"),
        (20, "secondary"),
        (21, "tertiary"),
        (24, "tertiary"),
    ],
)
def test_education_level(schl, level):
    assert _education_level(schl) == level


def test_assign_income_quintile_is_monotonic_and_balanced():
    df = pd.DataFrame({"PINCP": list(range(100)), "PWGTP": [1] * 100})
    q = assign_income_quintile(df)  # df is already income-sorted
    assert list(q) == sorted(q)  # quintile never decreases as income rises
    assert set(q) <= {1, 2, 3, 4, 5}
    counts = q.value_counts().to_dict()
    assert all(15 <= counts.get(k, 0) <= 25 for k in range(1, 6))  # ~20 each


def test_build_us_end_to_end(tmp_path, monkeypatch):
    raw = tmp_path / "us_pums.csv"
    pd.DataFrame(
        {
            "AGEP": [25, 45, 70, 17],  # the 17-year-old must be filtered out
            "SEX": [2, 1, 2, 1],
            "PINCP": [30000, 90000, 12000, 5000],
            "SCHL": [21, 16, 10, 19],
            "PWGTP": [100, 50, 80, 999],
        }
    ).to_csv(raw, index=False)

    out_csv = tmp_path / "us.csv"
    monkeypatch.setattr("pipeline.build_us._RAW", raw)
    monkeypatch.setattr("pipeline.build_us._OUT_CSV", out_csv)
    monkeypatch.setattr(
        "pipeline.build_us._OUT_META", out_csv.with_suffix(".meta.json")
    )

    build_us.build()

    joint = pd.read_csv(out_csv)
    assert set(joint.columns) == {
        "age_band",
        "gender",
        "education",
        "income_quintile",
        "weight",
    }
    assert abs(joint["weight"].sum() - 1.0) < 1e-9
    assert len(joint) == 3  # the under-18 row was dropped

    # the committed artifact flows straight into stage 2 via the storage seam
    monkeypatch.setattr("app.sampler._JOINT_DIR", tmp_path)
    people = sample_demographics(Locale.US, 20, seed=3)
    assert len(people) == 20
