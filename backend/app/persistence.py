"""Persist assembled personas to Postgres + pgvector.

The connection is injected (not built from settings) so this is testable against
a throwaway container without live credentials. Idempotent: re-running the seed
skips personas already present.
"""

from collections.abc import Iterable
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from app.assembly import AssembledPersona

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()


def apply_schema(conn: psycopg.Connection) -> None:
    """Create the pool schema if absent (idempotent — `CREATE … IF NOT EXISTS`),
    then check it is the current one.

    The check exists because `IF NOT EXISTS` silently accepts an out-of-date
    table, and the resulting failure is invisible: a full pre-006j pool makes
    every id a resume-skip, so no insert ever names the missing column and the run
    reports "0 written, 200 already present" over a pool with no summary vectors.
    """
    conn.execute(_SCHEMA_SQL)
    conn.commit()
    try:
        conn.execute("SELECT summary_embedding FROM personas LIMIT 0")
    except psycopg.errors.UndefinedColumn as error:
        conn.rollback()
        raise RuntimeError(
            "the personas table predates summary_embedding. Drop the database and "
            "reseed: the pool is a pure function of the master seed, so nothing "
            "is lost."
        ) from error


def prepare_connection(conn: psycopg.Connection) -> None:
    """Ready a connection for the pool: ensure the schema, then register the
    pgvector adapter so vector columns round-trip as numpy arrays. `register_vector`
    needs the extension to exist, so it must follow `apply_schema`.
    """
    apply_schema(conn)
    register_vector(conn)


def persist_persona(conn: psycopg.Connection, assembled: AssembledPersona) -> bool:
    """Write one persona and its summary vector; return whether it was newly written.

    `ON CONFLICT (id) DO NOTHING` makes a re-run a no-op for personas already
    present (returns False).
    """
    persona = assembled.persona
    big_five = persona.big_five
    with conn.transaction():
        result = conn.execute(
            """
            INSERT INTO personas (
                id, country, age, gender, income_quintile, education,
                openness, conscientiousness, extraversion, agreeableness,
                neuroticism, summary_embedding
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                persona.id,
                persona.country.value,
                persona.age,
                persona.gender,
                persona.income_quintile,
                persona.education.value,
                big_five.openness,
                big_five.conscientiousness,
                big_five.extraversion,
                big_five.agreeableness,
                big_five.neuroticism,
                np.array(assembled.summary_vector),
            ),
        )
    return result.rowcount == 1


def persist_pool(conn: psycopg.Connection, pool: Iterable[AssembledPersona]) -> int:
    """Persist every assembled persona (one transaction each); return the number
    newly written — personas already present are skipped and not counted."""
    return sum(persist_persona(conn, assembled) for assembled in pool)
