"""Post-seed QC report: anti-stereotype audit + plausibility eval over the pool.

Reads the persisted pool back from the DB, runs the two offline checks
(stereotype dispersion + plausibility G-Eval on a sample), and formats a
human-readable summary. Read-only — it measures the pool, never regenerates it.
"""

from dataclasses import dataclass

import numpy as np
import psycopg

from app.plausibility import Judge, PlausibilityReport, evaluate_sample
from app.schemas import BigFive, Persona
from app.stereotype_audit import (
    Axis,
    AxisReport,
    InterestObservation,
    Pool,
    audit_pool,
)


@dataclass(frozen=True)
class QCReport:
    audit: dict[Axis, AxisReport]
    plausibility: PlausibilityReport


def _age_band(age: int) -> str:
    """Decade band for grouping in the audit — 34 -> '30s'."""
    return f"{age // 10 * 10}s"


def load_audit_pool(conn: psycopg.Connection) -> Pool:
    """Read every (persona, interest) row + its embedding into an audit Pool."""
    rows = conn.execute(
        """
        SELECT p.id, p.country, p.age, p.gender, p.education, i.interest, i.embedding
        FROM personas p JOIN interests i ON i.persona_id = p.id
        ORDER BY p.id, i.interest
        """
    ).fetchall()
    observations = [
        InterestObservation(
            persona_id=pid,
            country=country,
            age_band=_age_band(age),
            gender=gender,
            education=education,
            interest=interest,
        )
        for pid, country, age, gender, education, interest, _ in rows
    ]
    vectors = np.array([row[6].to_numpy() for row in rows], dtype=np.float64)
    return Pool(observations=observations, vectors=vectors)


def load_persona_sample(conn: psycopg.Connection, *, limit: int) -> list[Persona]:
    """Reconstruct a random sample of full Persona objects for the plausibility judge."""
    persona_rows = conn.execute(
        """
        SELECT id, country, age, gender, income_quintile, education,
               openness, conscientiousness, extraversion, agreeableness, neuroticism
        FROM personas ORDER BY random() LIMIT %s
        """,
        (limit,),
    ).fetchall()
    if not persona_rows:
        return []
    ids = [row[0] for row in persona_rows]
    interests_by_id: dict[str, list[str]] = {}
    for pid, interest in conn.execute(
        "SELECT persona_id, interest FROM interests WHERE persona_id = ANY(%s)", (ids,)
    ):
        interests_by_id.setdefault(pid, []).append(interest)
    return [
        Persona(
            id=pid,
            country=country,
            age=age,
            gender=gender,
            income_quintile=income_quintile,
            education=education,
            interests=interests_by_id[pid],
            big_five=BigFive(
                openness=o,
                conscientiousness=c,
                extraversion=e,
                agreeableness=a,
                neuroticism=n,
            ),
        )
        for pid, country, age, gender, income_quintile, education, o, c, e, a, n in persona_rows
    ]


def run_qc(conn: psycopg.Connection, *, judge: Judge, sample_size: int) -> QCReport:
    """Audit the whole pool for stereotype collapse; judge a sample for plausibility."""
    audit = audit_pool(load_audit_pool(conn))
    plausibility = evaluate_sample(
        load_persona_sample(conn, limit=sample_size), judge=judge
    )
    return QCReport(audit=audit, plausibility=plausibility)


def format_qc_report(report: QCReport) -> str:
    lines = ["=== Pool QC ===", "Stereotype dispersion (lower = more collapsed):"]
    for axis, axis_report in report.audit.items():
        groups = ", ".join(
            f"{g.group} {g.dispersion:.2f} (n={g.size})" for g in axis_report.groups
        )
        lines.append(f"  {axis}: pool {axis_report.pool_dispersion:.2f} | {groups}")
    p = report.plausibility
    lines.append(
        f"Plausibility (n={p.n}): pass_rate {p.pass_rate:.2f}, "
        f"mean_rating {p.mean_rating:.2f}, {len(p.failures)} failures"
    )
    return "\n".join(lines)
