import numpy as np
import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from app.assembly import AssembledPersona
from app.persistence import (
    apply_schema,
    persist_persona,
    persist_pool,
    prepare_connection,
)
from app.schemas import BigFive, Persona

_DIM = 1536


@pytest.fixture(scope="module")
def pg_url():
    # pgvector image, not stock postgres — the stock image lacks the extension.
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


def _assembled(persona: Persona | None = None) -> AssembledPersona:
    persona = persona or _persona()
    vectors = [[float(i)] * _DIM for i in range(len(persona.interests))]
    return AssembledPersona(persona=persona, interest_vectors=vectors)


def _count(conn: psycopg.Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_persist_writes_persona_and_its_interests(conn):
    persist_persona(conn, _assembled())

    assert _count(conn, "personas") == 1
    assert _count(conn, "interests") == 2


def test_persist_is_idempotent_on_rerun(conn):
    persist_persona(conn, _assembled())
    persist_persona(conn, _assembled())  # same id — must be skipped, not duplicated

    assert _count(conn, "personas") == 1
    assert _count(conn, "interests") == 2


def test_embedding_round_trips_through_pgvector(conn):
    persona = _persona(interests=("hiking",))
    vector = [0.5] * _DIM
    persist_persona(conn, AssembledPersona(persona=persona, interest_vectors=[vector]))

    stored = conn.execute(
        "SELECT embedding FROM interests WHERE persona_id = %s", (persona.id,)
    ).fetchone()[0]
    restored = stored.to_numpy()
    assert restored.shape == (_DIM,)
    assert np.allclose(restored, vector)


def test_apply_schema_is_idempotent(conn):
    apply_schema(conn)
    apply_schema(conn)


def test_deleting_a_persona_cascades_to_its_interests(conn):
    persist_persona(conn, _assembled())
    conn.execute("DELETE FROM personas WHERE id = %s", ("US-00000",))
    conn.commit()

    assert _count(conn, "interests") == 0


def test_persist_pool_writes_all_and_returns_count(conn):
    pool = [
        _assembled(_persona(id_="US-00000")),
        _assembled(_persona(id_="US-00001")),
    ]

    assert persist_pool(conn, iter(pool)) == 2
    assert _count(conn, "personas") == 2
