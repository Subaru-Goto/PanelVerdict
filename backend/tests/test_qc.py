import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from app.assembly import AssembledPersona
from app.persistence import persist_persona, prepare_connection
from app.plausibility import PlausibilityReport, PlausibilityScore
from app.qc import (
    QCReport,
    _age_band,
    format_qc_report,
    load_audit_pool,
    load_persona_sample,
    run_qc,
)
from app.schemas import BigFive, Persona
from app.stereotype_audit import AXES, AxisReport, GroupDispersion

_DIM = 1536


class StubJudge:
    def score(self, *, prompt: str) -> PlausibilityScore:
        return PlausibilityScore(rating=5, reason="ok")


@pytest.fixture(scope="module")
def pg_url():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg.get_connection_url(driver=None)


@pytest.fixture
def conn(pg_url):
    with psycopg.connect(pg_url) as connection:
        prepare_connection(connection)
        connection.execute("TRUNCATE personas CASCADE")
        connection.commit()
        yield connection


def _persona(id_: str = "US-00000", interests=("hiking", "jazz")) -> Persona:
    return Persona(
        id=id_,
        country="US",
        age=34,
        gender="female",
        income_quintile=3,
        education="tertiary",
        interests=list(interests),
        big_five=BigFive(
            openness=0.1,
            conscientiousness=0.2,
            extraversion=-0.3,
            agreeableness=0.4,
            neuroticism=-0.5,
        ),
    )


def _assembled(persona: Persona) -> AssembledPersona:
    vectors = [[float(i)] * _DIM for i in range(len(persona.interests))]
    return AssembledPersona(persona=persona, interest_vectors=vectors)


def _seed(conn: psycopg.Connection, count: int) -> None:
    for i in range(count):
        persist_persona(conn, _assembled(_persona(id_=f"US-{i:05d}")))


def test_age_band_buckets_by_decade():
    assert _age_band(34) == "30s"
    assert _age_band(18) == "10s"
    assert _age_band(80) == "80s"


def test_load_audit_pool_builds_observations_and_vectors(conn):
    persist_persona(conn, _assembled(_persona(interests=("hiking", "jazz"))))

    pool = load_audit_pool(conn)

    assert len(pool.observations) == 2
    assert pool.vectors.shape == (2, _DIM)
    assert all(obs.age_band == "30s" for obs in pool.observations)  # age 34


def test_load_persona_sample_reconstructs_full_personas(conn):
    persist_persona(conn, _assembled(_persona(interests=("hiking", "jazz"))))

    sample = load_persona_sample(conn, limit=10)

    assert len(sample) == 1
    persona = sample[0]
    assert persona.id == "US-00000"
    assert set(persona.interests) == {"hiking", "jazz"}
    assert persona.big_five.openness == 0.1


def test_run_qc_produces_audit_and_plausibility(conn):
    _seed(conn, 3)

    report = run_qc(conn, judge=StubJudge(), sample_size=10)

    assert set(report.audit) == set(AXES)
    assert report.plausibility.n == 3  # sample_size > pool → all judged


def test_format_qc_report_summarizes_both_checks():
    report = QCReport(
        audit={"country": AxisReport("country", 0.42, [GroupDispersion("US", 6, 0.40)])},
        plausibility=PlausibilityReport(n=3, pass_rate=1.0, mean_rating=4.5, failures=[]),
    )

    text = format_qc_report(report)

    assert "country" in text and "0.42" in text
    assert "Plausibility (n=3)" in text
