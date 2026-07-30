import pytest

from app.assembly import (
    AssembledPersona,
    assemble_persona,
    assemble_pool,
    persona_id,
)
from app.panel import persona_summary
from app.sampler import JointCell
from app.schemas import Locale, Persona


class StubEmbedder:
    """One deterministic vector per text (no network), and a record of what it was
    asked to embed — so a test can assert the summary is what reaches the model."""

    def __init__(self, dim: int = 4) -> None:
        self._dim = dim
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[float(len(text))] * self._dim for text in texts]


_CELLS = [
    JointCell(
        age_band="20-29",
        gender="female",
        education="tertiary",
        income_quintile=4,
        weight=0.5,
    ),
    JointCell(
        age_band="30-39",
        gender="male",
        education="secondary",
        income_quintile=2,
        weight=0.5,
    ),
]


def _assemble(*, country=Locale.US, index=0, master_seed=7) -> AssembledPersona:
    return assemble_persona(
        country,
        index,
        _CELLS,
        master_seed=master_seed,
        embedder=StubEmbedder(),
    )


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

    assert isinstance(result, AssembledPersona)
    persona = result.persona
    assert isinstance(persona, Persona)
    assert persona.id == "US-00003"
    assert persona.country is Locale.US
    assert isinstance(persona.big_five.openness, float)
    assert len(result.summary_embedding) == 4


def test_assemble_persona_is_reproducible_for_a_seed() -> None:
    first = _assemble(index=5, master_seed=99)
    second = _assemble(index=5, master_seed=99)

    assert first.persona == second.persona
    assert first.summary_embedding == second.summary_embedding


def test_distinct_slots_draw_different_people() -> None:
    # per-slot seeding: slot 0 and slot 1 get independent Big Five draws
    assert _assemble(index=0).persona.big_five != _assemble(index=1).persona.big_five


def test_assemble_pool_respects_quotas_and_orders_ids(joint_dir) -> None:
    pool = list(
        assemble_pool(
            {Locale.US: 3, Locale.JP: 2},
            master_seed=1,
            embedder=StubEmbedder(),
        )
    )

    assert [ap.persona.id for ap in pool] == [
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
            embedder=StubEmbedder(),
            skip={"US-00001"},
        )
    )

    assert [ap.persona.id for ap in partial] == ["US-00000", "US-00002"]


def test_dev_subset_is_a_prefix_of_the_full_pool(joint_dir) -> None:
    # slot i is the same person at any pool size, so a smaller run is a true
    # prefix of a larger one (D3 per-slot seeding) — validate dev, ship full.
    def build(n: int) -> list[Persona]:
        return [
            ap.persona
            for ap in assemble_pool(
                {Locale.US: n},
                master_seed=1,
                embedder=StubEmbedder(),
            )
        ]

    assert build(2) == build(5)[:2]


def test_the_embedded_text_is_the_persona_summary() -> None:
    # what the panelist search matches against must be the rendered summary,
    # not some other framing
    embedder = StubEmbedder()

    result = assemble_persona(Locale.US, 0, _CELLS, master_seed=7, embedder=embedder)

    assert embedder.texts == [persona_summary(result.persona)]
