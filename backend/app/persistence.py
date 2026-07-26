"""Persist assembled personas to Postgres + pgvector.

The connection is injected (not built from settings) so this is testable against
a throwaway container without live credentials. Idempotent: re-running the seed
skips personas already present.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.assembly import AssembledPersona
from app.schemas import BigFive, Persona


class PersonaRow(TypedDict):
    """One `personas` row as the readers below select it.

    Spelling the shape out rather than passing `dict[str, object]` around keeps the
    SELECT and the field reads in one place: adding a column to `_PERSONA_COLUMNS`
    without adding it here is then a type error rather than a KeyError at runtime.
    """

    id: str
    country: str
    age: int
    gender: str
    income_quintile: int
    education: str
    openness: float
    conscientiousness: float
    extraversion: float
    agreeableness: float
    neuroticism: float


_PERSONA_COLUMNS = ", ".join(PersonaRow.__annotations__)

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()

# Columns added after the first schema shipped. `CREATE TABLE IF NOT EXISTS` will
# not add them to an existing table, so `apply_schema` probes for them; extend this
# whenever a column is added rather than writing a second probe.
_REQUIRED_COLUMNS = ("summary_embedding",)


def apply_schema(conn: psycopg.Connection) -> None:
    """Create the pool schema if absent (idempotent), then refuse a stale one.

    `CREATE … IF NOT EXISTS` silently accepts an out-of-date table, and the
    resulting failure is invisible rather than loud: a full pre-006j pool makes
    every id a resume-skip, so no insert ever names the missing column and the run
    reports "0 written, 200 already present" over a pool with no embeddings.
    """
    conn.execute(_SCHEMA_SQL)
    conn.commit()
    try:
        conn.execute(f"SELECT {', '.join(_REQUIRED_COLUMNS)} FROM personas LIMIT 0")
    except psycopg.errors.UndefinedColumn as error:
        conn.rollback()
        raise RuntimeError(
            "the personas table is missing a column this build writes "
            f"({', '.join(_REQUIRED_COLUMNS)}). Drop the database and reseed: the "
            "sampled columns are a pure function of the master seed, so no "
            "information is lost."
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
                np.array(assembled.summary_embedding),
            ),
        )
    return result.rowcount == 1


def persist_pool(conn: psycopg.Connection, pool: Iterable[AssembledPersona]) -> int:
    """Persist every assembled persona (one transaction each); return the number
    newly written — personas already present are skipped and not counted."""
    return sum(persist_persona(conn, assembled) for assembled in pool)


def _persona_from_row(row: PersonaRow) -> Persona:
    """Rebuild a Persona from its columns. The summary embedding is deliberately
    not read back — it is derived from these fields, and no reader needs both."""
    return Persona(
        id=row["id"],
        country=row["country"],
        age=row["age"],
        gender=row["gender"],
        income_quintile=row["income_quintile"],
        education=row["education"],
        big_five=BigFive(
            openness=row["openness"],
            conscientiousness=row["conscientiousness"],
            extraversion=row["extraversion"],
            agreeableness=row["agreeableness"],
            neuroticism=row["neuroticism"],
        ),
    )


def _read_personas(
    conn: psycopg.Connection, clause: str, params: tuple = ()
) -> list[Persona]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            f"SELECT {_PERSONA_COLUMNS} FROM personas {clause}", params
        ).fetchall()
    return [_persona_from_row(cast(PersonaRow, row)) for row in rows]


def load_pool(conn: psycopg.Connection) -> list[Persona]:
    """Every persona, in id order — the aggregate view pool QC audits."""
    return _read_personas(conn, "ORDER BY id")


def load_persona_sample(conn: psycopg.Connection, *, limit: int) -> list[Persona]:
    """A random sample, for the plausibility judge — which pays per persona, so it
    reads a sample rather than the pool."""
    return _read_personas(conn, "ORDER BY random() LIMIT %s", (limit,))
