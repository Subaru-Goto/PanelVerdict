import numpy as np
import psycopg
import pytest
from factories import DIM, make_assembled, make_persona

from app.assembly import AssembledPersona
from app.persistence import (
    apply_schema,
    persist_persona,
    persist_pool,
    prepare_connection,
)


def _count(conn: psycopg.Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_persist_writes_one_row_per_persona(conn):
    persist_persona(conn, make_assembled())

    assert _count(conn, "personas") == 1


def test_persist_is_idempotent_on_rerun(conn):
    assert persist_persona(conn, make_assembled()) is True
    assert persist_persona(conn, make_assembled()) is False

    assert _count(conn, "personas") == 1


def test_summary_embedding_round_trips_through_pgvector(conn):
    persona = make_persona()
    vector = [0.5] * DIM
    persist_persona(conn, AssembledPersona(persona=persona, summary_vector=vector))

    stored = conn.execute(
        "SELECT summary_embedding FROM personas WHERE id = %s", (persona.id,)
    ).fetchone()[0]
    restored = stored.to_numpy()
    assert restored.shape == (DIM,)
    assert np.allclose(restored, vector)


def test_apply_schema_is_idempotent(conn):
    apply_schema(conn)
    apply_schema(conn)


def test_apply_schema_refuses_a_table_that_predates_summary_embedding(conn):
    # CREATE TABLE IF NOT EXISTS accepts a stale table, and the failure is
    # otherwise invisible: a full old pool makes every id a resume-skip, so no
    # insert ever names the missing column and the seed reports success.
    # Restores the real schema afterwards — the container is module-scoped.
    conn.execute("DROP TABLE personas CASCADE")
    conn.execute("CREATE TABLE personas (id text PRIMARY KEY)")
    conn.commit()
    try:
        with pytest.raises(RuntimeError, match="predates summary_embedding"):
            apply_schema(conn)
    finally:
        conn.execute("DROP TABLE personas")
        conn.commit()
        apply_schema(conn)


def test_a_wrong_dimension_vector_writes_nothing(conn):
    # the vector is now a column on the persona row rather than a child table, so
    # a bad dimension must fail the whole insert instead of half-writing it
    bad = AssembledPersona(persona=make_persona(), summary_vector=[0.1] * (DIM + 1))

    with pytest.raises(psycopg.Error):
        persist_persona(conn, bad)
    assert _count(conn, "personas") == 0


def test_persist_commits_per_persona_on_an_autocommit_connection(pg_url):
    # the seed CLI's connection mode: each persisted persona must be durable
    # (visible to another connection) immediately, so an interrupted run keeps
    # everything already written. On a non-autocommit connection the per-persona
    # transaction would silently be a savepoint in one run-long transaction.
    with psycopg.connect(pg_url, autocommit=True) as writer:
        prepare_connection(writer)
        writer.execute("TRUNCATE personas CASCADE")
        persist_persona(writer, make_assembled())
        with psycopg.connect(pg_url) as reader:
            assert _count(reader, "personas") == 1


def test_persist_pool_writes_all_and_returns_count(conn):
    pool = [
        make_assembled(make_persona(id_="US-00000")),
        make_assembled(make_persona(id_="US-00001")),
    ]

    assert persist_pool(conn, iter(pool)) == 2
    assert _count(conn, "personas") == 2


def test_persist_pool_counts_only_new_writes_on_rerun(conn):
    pool = [
        make_assembled(make_persona(id_="US-00000")),
        make_assembled(make_persona(id_="US-00001")),
    ]

    assert persist_pool(conn, pool) == 2
    assert persist_pool(conn, pool) == 0
    assert _count(conn, "personas") == 2
