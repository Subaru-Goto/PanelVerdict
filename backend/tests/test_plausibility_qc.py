"""The DB-backed half of plausibility QC: read a sample back, judge it, format it."""

import psycopg
from factories import make_assembled, make_persona

from app.persistence import persist_persona
from app.plausibility import (
    PlausibilityReport,
    PlausibilityScore,
    format_report,
    load_persona_sample,
    run_plausibility_qc,
)


class StubJudge:
    def score(self, *, prompt: str) -> PlausibilityScore:
        return PlausibilityScore(rating=5, reason="ok")


def _seed(conn: psycopg.Connection, count: int) -> None:
    for i in range(count):
        persist_persona(conn, make_assembled(make_persona(id_=f"US-{i:05d}")))


def test_load_persona_sample_rebuilds_personas_from_their_columns(conn):
    persist_persona(conn, make_assembled(make_persona()))

    sample = load_persona_sample(conn, limit=10)

    assert len(sample) == 1
    persona = sample[0]
    assert persona.id == "US-00000"
    assert persona.big_five.openness == 0.1


def test_run_plausibility_qc_judges_the_sample(conn):
    _seed(conn, 3)

    report = run_plausibility_qc(conn, judge=StubJudge(), sample_size=10)

    assert report.n == 3  # sample_size > pool → all judged


def test_format_report_summarizes_the_check():
    report = PlausibilityReport(n=3, pass_rate=1.0, mean_rating=4.5, failures=[])

    text = format_report(report)

    assert "Plausibility (n=3)" in text
    assert "4.50" in text
