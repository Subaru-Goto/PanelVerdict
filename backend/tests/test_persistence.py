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


def test_persist_writes_persona_and_its_interests(conn):
    persist_persona(conn, make_assembled())

    assert _count(conn, "personas") == 1
    assert _count(conn, "interests") == 2


def test_persist_is_idempotent_on_rerun(conn):
    persist_persona(conn, make_assembled())
    persist_persona(conn, make_assembled())

    assert _count(conn, "personas") == 1
    assert _count(conn, "interests") == 2


def test_embedding_round_trips_through_pgvector(conn):
    persona = make_persona(interests=("hiking",))
    vector = [0.5] * DIM
    persist_persona(conn, AssembledPersona(persona=persona, interest_vectors=[vector]))

    stored = conn.execute(
        "SELECT embedding FROM interests WHERE persona_id = %s", (persona.id,)
    ).fetchone()[0]
    restored = stored.to_numpy()
    assert restored.shape == (DIM,)
    assert np.allclose(restored, vector)


def test_apply_schema_is_idempotent(conn):
    apply_schema(conn)
    apply_schema(conn)


def test_deleting_a_persona_cascades_to_its_interests(conn):
    persist_persona(conn, make_assembled())
    conn.execute("DELETE FROM personas WHERE id = %s", ("US-00000",))
    conn.commit()

    assert _count(conn, "interests") == 0


def test_persona_and_interests_write_atomically(conn):
    # a wrong-dimension vector fails the interests insert; the persona row must
    # roll back with it, never left orphaned
    persona = make_persona(interests=("hiking",))
    bad = AssembledPersona(persona=persona, interest_vectors=[[0.1] * (DIM + 1)])

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
