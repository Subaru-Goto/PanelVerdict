import pytest

from app.assembly import (
    assemble_persona,
    assemble_pool,
    persona_id,
)
from app.sampler import JointCell
from app.schemas import EducationLevel, Locale, Persona


_CELLS = [
    JointCell(
        age_band="20-29",
        gender="female",
        education=EducationLevel.TERTIARY,
        income_quintile=4,
        weight=0.5,
    ),
    JointCell(
        age_band="30-39",
        gender="male",
        education=EducationLevel.SECONDARY,
        income_quintile=2,
        weight=0.5,
    ),
]


def _assemble(*, country=Locale.US, index=0, master_seed=7) -> Persona:
    return assemble_persona(country, index, _CELLS, master_seed=master_seed)


@pytest.fixture
def joint_dir(tmp_path, monkeypatch):
    joint = tmp_path / "joint"
    joint.mkdir()
    rows = (
        "age_band,gender,education,income_quintile,weight\n"
        "20-29,female,tertiary,4,0.5\n"
        "30-39,male,secondary,2,0.5\n"
    )
    for country in ("us", "jp", "de"):
        (joint / f"{country}.csv").write_text(rows)
    monkeypatch.setattr("app.sampler._JOINT_DIR", joint)
    return tmp_path


def test_persona_id_is_country_prefixed_and_zero_padded() -> None:
    assert persona_id(Locale.US, 42) == "US-00042"
    assert persona_id(Locale.JP, 0) == "JP-00000"


def test_assemble_persona_composes_the_full_pipeline() -> None:
    result = _assemble(index=3)

    assert isinstance(result, Persona)
    assert result.id == "US-00003"
    assert result.country is Locale.US
    assert isinstance(result.big_five.openness, float)


def test_assemble_persona_is_reproducible_for_a_seed() -> None:
    first = _assemble(index=5, master_seed=99)
    second = _assemble(index=5, master_seed=99)

    assert first == second


def test_distinct_slots_draw_different_people() -> None:
    # per-slot seeding: slot 0 and slot 1 get independent Big Five draws
    assert _assemble(index=0).big_five != _assemble(index=1).big_five


def test_assemble_pool_respects_quotas_and_orders_ids(joint_dir) -> None:
    pool = list(
        assemble_pool(
            {Locale.US: 3, Locale.JP: 2},
            master_seed=1,
        )
    )

    assert [persona.id for persona in pool] == [
        "US-00000",
        "US-00001",
        "US-00002",
        "JP-00000",
        "JP-00001",
    ]


def test_assemble_pool_skips_given_ids(joint_dir) -> None:
    partial = list(
        assemble_pool(
            {Locale.US: 3},
            master_seed=1,
            skip={"US-00001"},
        )
    )

    assert [persona.id for persona in partial] == ["US-00000", "US-00002"]


def test_dev_subset_is_a_prefix_of_the_full_pool(joint_dir) -> None:
    # slot i is the same person at any pool size, so a smaller run is a true
    # prefix of a larger one (D3 per-slot seeding) — validate dev, ship full.
    def build(n: int) -> list[Persona]:
        return list(assemble_pool({Locale.US: n}, master_seed=1))

    assert build(2) == build(5)[:2]
