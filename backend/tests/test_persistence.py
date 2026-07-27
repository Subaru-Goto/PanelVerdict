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
    retrieve_panel,
)
from app.schemas import EducationLevel, Locale, TargetRequest
from app.targeting import resolve_target


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
    persist_persona(conn, AssembledPersona(persona=persona, summary_embedding=vector))

    stored = conn.execute(
        "SELECT summary_embedding FROM personas WHERE id = %s", (persona.id,)
    ).fetchone()[0]
    restored = stored.to_numpy()
    assert restored.shape == (DIM,)
    assert np.allclose(restored, vector)


def test_apply_schema_is_idempotent(conn):
    apply_schema(conn)
    apply_schema(conn)


def test_apply_schema_refuses_a_table_missing_a_column_it_writes(conn):
    # CREATE TABLE IF NOT EXISTS accepts a stale table, and the failure is
    # otherwise invisible: a full old pool makes every id a resume-skip, so no
    # insert ever names the missing column and the seed reports success.
    # Restores the real schema afterwards — the container is module-scoped.
    conn.execute("DROP TABLE personas CASCADE")
    conn.execute("CREATE TABLE personas (id text PRIMARY KEY)")
    conn.commit()
    try:
        with pytest.raises(RuntimeError, match="missing a column"):
            apply_schema(conn)
    finally:
        conn.execute("DROP TABLE personas")
        conn.commit()
        apply_schema(conn)


def test_a_wrong_dimension_vector_writes_nothing(conn):
    # the vector is now a column on the persona row rather than a child table, so
    # a bad dimension must fail the whole insert instead of half-writing it
    bad = AssembledPersona(persona=make_persona(), summary_embedding=[0.1] * (DIM + 1))

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


def _vector(*head: float) -> list[float]:
    """A DIM-length vector with the given leading components, zeroes after."""
    return list(head) + [0.0] * (DIM - len(head))


# The whole pool, unfiltered — every retrieval test narrows this rather than
# assembling eight fields, so what each one is actually about stays visible.
_EVERYONE = resolve_target(TargetRequest())


def _seed_pool(conn: psycopg.Connection, *assembled: AssembledPersona) -> None:
    persist_pool(conn, assembled)


def test_retrieval_filters_on_country(conn):
    _seed_pool(
        conn,
        make_assembled(make_persona(id_="US-00000", country="US")),
        make_assembled(make_persona(id_="JP-00000", country="JP")),
    )

    panel = retrieve_panel(
        conn, _EVERYONE.model_copy(update={"countries": (Locale.JP,)}), size=10, seed=0
    )

    assert [p.id for p in panel] == ["JP-00000"]


def test_no_coverage_retrieves_nobody(conn):
    """An empty `countries` is the ladder's bottom rung, not a missing filter. The
    dangerous failure would be reading it as "no country constraint" and returning a
    random panel that looks like a matched one."""
    _seed_pool(conn, make_assembled(make_persona(id_="US-00000")))

    assert (
        retrieve_panel(
            conn, _EVERYONE.model_copy(update={"countries": ()}), size=10, seed=0
        )
        == []
    )


def test_retrieval_filters_on_the_age_span(conn):
    _seed_pool(
        conn,
        make_assembled(make_persona(id_="US-00000", age=29)),
        make_assembled(make_persona(id_="US-00001", age=30)),
        make_assembled(make_persona(id_="US-00002", age=39)),
        make_assembled(make_persona(id_="US-00003", age=40)),
    )

    panel = retrieve_panel(
        conn,
        _EVERYONE.model_copy(update={"min_age": 30, "max_age": 39}),
        size=10,
        seed=0,
    )

    assert sorted(p.age for p in panel) == [30, 39]


def test_an_inverted_age_span_retrieves_nobody(conn):
    """What "under 18" clamps to. It has to match nobody rather than everybody."""
    _seed_pool(conn, make_assembled(make_persona(id_="US-00000", age=34)))

    panel = retrieve_panel(
        conn,
        _EVERYONE.model_copy(update={"min_age": 18, "max_age": 17}),
        size=10,
        seed=0,
    )

    assert panel == []


def test_retrieval_filters_on_gender_income_and_education(conn):
    wanted = make_persona(
        id_="US-00000", gender="male", income_quintile=5, education="secondary"
    )
    _seed_pool(
        conn,
        make_assembled(wanted),
        make_assembled(make_persona(id_="US-00001", gender="female")),
        make_assembled(make_persona(id_="US-00002", gender="male", income_quintile=1)),
        make_assembled(
            make_persona(
                id_="US-00003",
                gender="male",
                income_quintile=5,
                education="tertiary",
            )
        ),
    )

    panel = retrieve_panel(
        conn,
        _EVERYONE.model_copy(
            update={
                "gender": "male",
                "income_quintiles": (4, 5),
                "education": (EducationLevel.SECONDARY,),
            }
        ),
        size=10,
        seed=0,
    )

    assert [p.id for p in panel] == ["US-00000"]


def test_a_disposition_orders_the_panel_by_similarity(conn):
    """The vector half. Ordering, not filtering — every persona in the filtered set
    is a candidate, and the query decides who is closest."""
    _seed_pool(
        conn,
        make_assembled(make_persona(id_="US-00000"), embedding=_vector(0.0, 1.0)),
        make_assembled(make_persona(id_="US-00001"), embedding=_vector(1.0, 1.0)),
        make_assembled(make_persona(id_="US-00002"), embedding=_vector(1.0, 0.0)),
    )

    panel = retrieve_panel(
        conn, _EVERYONE, size=3, seed=0, disposition_embedding=_vector(1.0, 0.0)
    )

    assert [p.id for p in panel] == ["US-00002", "US-00001", "US-00000"]


def test_size_caps_the_panel_at_the_closest_matches(conn):
    _seed_pool(
        conn,
        make_assembled(make_persona(id_="US-00000"), embedding=_vector(0.0, 1.0)),
        make_assembled(make_persona(id_="US-00001"), embedding=_vector(1.0, 1.0)),
        make_assembled(make_persona(id_="US-00002"), embedding=_vector(1.0, 0.0)),
    )

    panel = retrieve_panel(
        conn, _EVERYONE, size=2, seed=0, disposition_embedding=_vector(1.0, 0.0)
    )

    assert [p.id for p in panel] == ["US-00002", "US-00001"]


def test_equal_distances_break_ties_deterministically(conn):
    """The pool holds duplicate summaries — two 34-year-olds with the same rendered
    levels embed identically. Without a tiebreak the panel would vary run to run for
    no reason the customer could see."""
    _seed_pool(
        conn,
        make_assembled(make_persona(id_="US-00002"), embedding=_vector(1.0)),
        make_assembled(make_persona(id_="US-00000"), embedding=_vector(1.0)),
        make_assembled(make_persona(id_="US-00001"), embedding=_vector(1.0)),
    )

    ids = [
        [
            p.id
            for p in retrieve_panel(
                conn, _EVERYONE, size=2, seed=0, disposition_embedding=_vector(1.0)
            )
        ]
        for _ in range(3)
    ]

    assert ids == [["US-00000", "US-00001"]] * 3


def _numbered_pool(conn: psycopg.Connection, count: int) -> None:
    _seed_pool(
        conn,
        *(make_assembled(make_persona(id_=f"US-{i:05d}")) for i in range(count)),
    )


def test_a_target_with_no_disposition_draws_a_reproducible_sample(conn):
    _numbered_pool(conn, 10)

    first = [p.id for p in retrieve_panel(conn, _EVERYONE, size=4, seed=7)]
    again = [p.id for p in retrieve_panel(conn, _EVERYONE, size=4, seed=7)]

    assert first == again
    assert len(first) == 4


def test_the_seed_chooses_who_is_sampled(conn):
    """Reproducible must not mean fixed: two tests of the same target should be able
    to draw different panels, which is what makes sample-stability measurable."""
    _numbered_pool(conn, 10)

    drawn = {
        tuple(p.id for p in retrieve_panel(conn, _EVERYONE, size=4, seed=seed))
        for seed in range(5)
    }

    assert len(drawn) > 1
    # and it is a sample, not the first four ids in a different order
    assert drawn != {tuple(f"US-{i:05d}" for i in range(4))}


def test_a_panel_larger_than_the_pool_returns_what_exists(conn):
    """Which is what makes the shortfall reportable rather than an error."""
    _numbered_pool(conn, 3)

    assert len(retrieve_panel(conn, _EVERYONE, size=200, seed=0)) == 3


def test_a_panel_size_below_one_is_rejected(conn):
    with pytest.raises(ValueError):
        retrieve_panel(conn, _EVERYONE, size=0, seed=0)
