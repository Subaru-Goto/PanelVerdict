from typing import get_args

import numpy as np
import psycopg
import pytest
from factories import DIM, big_five, make_assembled, make_persona

from app.assembly import AssembledPersona
from app.persistence import (
    apply_schema,
    load_votes,
    persist_persona,
    persist_pool,
    prepare_connection,
    retrieve_panel,
    store_votes,
)
from app.schemas import (
    EducationLevel,
    Locale,
    TargetQuery,
    TargetRequest,
    TraitLevel,
    TraitName,
    TraitRequest,
    VoteRecord,
)
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


# The whole pool, unfiltered — every retrieval test narrows this rather than
# assembling eight fields, so what each one is actually about stays visible.
_EVERYONE = resolve_target(TargetRequest())


def test_retrieval_filters_on_country(conn):
    persist_pool(
        conn,
        [
            make_assembled(make_persona(id_="US-00000", country="US")),
            make_assembled(make_persona(id_="JP-00000", country="JP")),
        ],
    )

    panel = retrieve_panel(
        conn, _EVERYONE.model_copy(update={"countries": (Locale.JP,)}), size=10, seed=0
    )

    assert [p.id for p in panel] == ["JP-00000"]


def test_no_coverage_retrieves_nobody(conn):
    """An empty `countries` is the ladder's bottom rung, not a missing filter. The
    dangerous failure would be reading it as "no country constraint" and returning a
    random panel that looks like a matched one."""
    persist_pool(conn, [make_assembled(make_persona(id_="US-00000"))])

    assert (
        retrieve_panel(
            conn, _EVERYONE.model_copy(update={"countries": ()}), size=10, seed=0
        )
        == []
    )


def test_retrieval_filters_on_the_age_span(conn):
    persist_pool(
        conn,
        [
            make_assembled(make_persona(id_="US-00000", age=29)),
            make_assembled(make_persona(id_="US-00001", age=30)),
            make_assembled(make_persona(id_="US-00002", age=39)),
            make_assembled(make_persona(id_="US-00003", age=40)),
        ],
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
    persist_pool(conn, [make_assembled(make_persona(id_="US-00000", age=34))])

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
    persist_pool(
        conn,
        [
            make_assembled(wanted),
            make_assembled(make_persona(id_="US-00001", gender="female")),
            make_assembled(
                make_persona(id_="US-00002", gender="male", income_quintile=1)
            ),
            make_assembled(
                make_persona(
                    id_="US-00003",
                    gender="male",
                    income_quintile=5,
                    education="tertiary",
                )
            ),
        ],
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


def _with_trait(trait: TraitName, score: float, id_: str) -> AssembledPersona:
    return make_assembled(make_persona(id_=id_, big_five=big_five(**{trait: score})))


def _requesting(trait: TraitName, level: TraitLevel) -> TargetQuery:
    return _EVERYONE.model_copy(
        update={
            "traits": (TraitRequest(trait=trait, level=level, source_phrase="stub"),)
        }
    )


def test_a_requested_trait_level_filters_rather_than_ranks(conn):
    """A target asking for anxious people gets only anxious people, not the pool sorted
    by how anxious it is. Ranking would return the extreme tail, and skew the panel on
    the four traits nobody asked about."""
    persist_pool(
        conn,
        [
            _with_trait("neuroticism", 1.0, "US-00000"),
            _with_trait("neuroticism", 0.0, "US-00001"),
            _with_trait("neuroticism", -2.0, "US-00002"),
        ],
    )

    panel = retrieve_panel(
        conn, _requesting("neuroticism", TraitLevel.HIGH), size=10, seed=0
    )

    assert [p.id for p in panel] == ["US-00000"]


def test_a_requested_level_admits_the_levels_beyond_it(conn):
    """Asking for cautious people must not exclude the most cautious of them, so a
    `very_high` score is inside `high`'s bound rather than past it."""
    persist_pool(
        conn,
        [
            _with_trait("openness", 1.0, "US-00000"),  # high
            _with_trait("openness", 2.5, "US-00001"),  # very_high
        ],
    )

    panel = retrieve_panel(
        conn, _requesting("openness", TraitLevel.HIGH), size=10, seed=0
    )

    assert [p.id for p in panel] == ["US-00000", "US-00001"]


def test_a_requested_middle_level_excludes_both_tails(conn):
    """`medium` is the one level that is a band rather than a direction, so it needs
    two bounds — one of them alone would admit half the pool."""
    persist_pool(
        conn,
        [
            _with_trait("extraversion", -2.0, "US-00000"),
            _with_trait("extraversion", 0.0, "US-00001"),
            _with_trait("extraversion", 2.0, "US-00002"),
        ],
    )

    panel = retrieve_panel(
        conn, _requesting("extraversion", TraitLevel.MEDIUM), size=10, seed=0
    )

    assert [p.id for p in panel] == ["US-00001"]


@pytest.mark.parametrize(
    ("score", "admits", "refuses"),
    [
        (0.5, TraitLevel.MEDIUM, TraitLevel.HIGH),
        (1.5, TraitLevel.HIGH, TraitLevel.VERY_HIGH),
        (-0.5, TraitLevel.MEDIUM, TraitLevel.LOW),
        (-1.5, TraitLevel.LOW, TraitLevel.VERY_LOW),
    ],
)
def test_a_score_on_a_boundary_matches_the_level_it_renders_as(
    conn, score, admits, refuses
):
    """The one thing a Python check of the bounds cannot establish: that Postgres
    compares them the way the table means. Every boundary belongs to the inner band, so
    the level a score renders as must admit it and the level beyond must refuse it —
    and these four scores are where a `>` written as `>=` on either side would show.
    """
    persist_pool(conn, [_with_trait("openness", score, "US-00000")])

    assert retrieve_panel(conn, _requesting("openness", admits), size=10, seed=0)
    assert retrieve_panel(conn, _requesting("openness", refuses), size=10, seed=0) == []


def test_two_requested_traits_both_have_to_match(conn):
    """Each trait multiplies the filter, which is where a thin panel comes from —
    reporting that is the caller's job, so retrieval only has to be exact."""
    persist_pool(
        conn,
        [
            make_assembled(
                make_persona(
                    id_="US-00000",
                    big_five=big_five(openness=1.0, neuroticism=-1.0),
                )
            ),
            _with_trait("openness", 1.0, "US-00001"),
        ],
    )

    query = _EVERYONE.model_copy(
        update={
            "traits": (
                TraitRequest(
                    trait="openness", level=TraitLevel.HIGH, source_phrase="a"
                ),
                TraitRequest(
                    trait="neuroticism", level=TraitLevel.LOW, source_phrase="b"
                ),
            )
        }
    )

    assert [p.id for p in retrieve_panel(conn, query, size=10, seed=0)] == ["US-00000"]


def test_a_trait_filter_still_draws_a_sample_rather_than_a_ranking(conn):
    """Nothing is ranked, so the seed reaches a target that names a temperament too.
    That is what makes two independent draws of one target possible, and with them the
    sample-stability check."""
    persist_pool(
        conn,
        [_with_trait("openness", 1.0, f"US-{i:05d}") for i in range(10)],
    )
    query = _requesting("openness", TraitLevel.HIGH)

    drawn = {
        tuple(p.id for p in retrieve_panel(conn, query, size=4, seed=seed))
        for seed in range(5)
    }

    assert len(drawn) > 1


def _numbered_pool(conn: psycopg.Connection, count: int) -> None:
    persist_pool(
        conn,
        list(make_assembled(make_persona(id_=f"US-{i:05d}")) for i in range(count)),
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


def test_size_caps_the_panel(conn):
    _numbered_pool(conn, 10)

    assert len(retrieve_panel(conn, _EVERYONE, size=4, seed=0)) == 4


def test_every_trait_a_target_can_name_is_a_column(conn):
    """The trait name is interpolated into the WHERE clause as the column name. It is
    a closed Literal, so no caller can reach the SQL text — but a trait renamed on one
    side only would be an UndefinedColumn at the first real target."""
    columns = {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'personas'"
        ).fetchall()
    }

    assert set(get_args(TraitName)) <= columns


def _vote_record(reason: str = "liked it") -> VoteRecord:
    return VoteRecord(
        persona_id="JP-00001",
        test_id="t1",
        chosen_variant_id="a",
        presentation_order=["a", "b"],
        reason=reason,
    )


def test_a_stored_vote_loads_back_whole(conn):
    record = _vote_record()
    assert store_votes(conn, {"fp1": record}) == 1

    assert load_votes(conn, ["fp1"]) == {"fp1": record}


def test_load_returns_only_the_fingerprints_that_exist(conn):
    store_votes(conn, {"fp1": _vote_record()})

    assert load_votes(conn, ["fp1", "fp-unknown"]).keys() == {"fp1"}
    assert load_votes(conn, []) == {}


def test_the_ledger_is_append_only(conn):
    """Votes are paid model output — the one table not regenerable from a seed
    (010e's ruling). A colliding write must leave the original untouched, never
    replace it: the first vote under a fingerprint is THE vote for that question."""
    store_votes(conn, {"fp1": _vote_record(reason="first")})

    assert store_votes(conn, {"fp1": _vote_record(reason="second")}) == 0
    assert load_votes(conn, ["fp1"])["fp1"].reason == "first"
