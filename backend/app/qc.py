"""Post-seed QC report: plausibility eval over a sample of the pool.

Reads the persisted pool back from the DB, judges a sample, and formats a
human-readable summary. Read-only — it measures the pool, never regenerates it.

The stereotype-dispersion half is gone with interests (006j): cosine dispersion
over generated interest text cannot measure a pool whose every field is sampled
from a published table. What replaces it is comparing realized distributions
against the priors they were drawn from, which belongs to 006g.
"""

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from app.plausibility import Judge, PlausibilityReport, evaluate_sample
from app.schemas import BigFive, Persona


@dataclass(frozen=True)
class QCReport:
    plausibility: PlausibilityReport


def load_persona_sample(conn: psycopg.Connection, *, limit: int) -> list[Persona]:
    """Reconstruct a random sample of full Persona objects for the plausibility judge."""
    with conn.cursor(row_factory=dict_row) as cur:
        persona_rows = cur.execute(
            """
            SELECT id, country, age, gender, income_quintile, education,
                   openness, conscientiousness, extraversion, agreeableness, neuroticism
            FROM personas ORDER BY random() LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [
        Persona(
            id=r["id"],
            country=r["country"],
            age=r["age"],
            gender=r["gender"],
            income_quintile=r["income_quintile"],
            education=r["education"],
            big_five=BigFive(
                openness=r["openness"],
                conscientiousness=r["conscientiousness"],
                extraversion=r["extraversion"],
                agreeableness=r["agreeableness"],
                neuroticism=r["neuroticism"],
            ),
        )
        for r in persona_rows
    ]


def run_qc(conn: psycopg.Connection, *, judge: Judge, sample_size: int) -> QCReport:
    """Judge a random sample of the pool for plausibility."""
    return QCReport(
        plausibility=evaluate_sample(
            load_persona_sample(conn, limit=sample_size), judge=judge
        )
    )


def format_qc_report(report: QCReport) -> str:
    p = report.plausibility
    return (
        "=== Pool QC ===\n"
        f"Plausibility (n={p.n}): pass_rate {p.pass_rate:.2f}, "
        f"mean_rating {p.mean_rating:.2f}, {len(p.failures)} failures"
    )
