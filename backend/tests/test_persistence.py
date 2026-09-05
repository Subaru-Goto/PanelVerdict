from pathlib import Path
from urllib.parse import urlsplit
from typing import get_args

import psycopg
import pytest
from psycopg.pq import TransactionStatus
from tests.factories import (
    big_five,
    make_persona,
    make_report,
)

import app.persistence
from app.persistence import (
    _PERSONA_COLUMNS,
    FEEDBACK_QUERY,
    store_feedback,
    anyone_matches,
    REPORT_SCHEMA_VERSION,
    apply_schema,
    deny_data_api,
    missing_columns,
    load_pool,
    count_reports,
    load_votes,
    persist_persona,
    persist_pool,
    prepare_connection,
    delete_report,
    delete_reports_of,
    list_reports,
    load_report,
    retrieve_panel,
    schema_columns,
    store_report,
    sweep_unkept_reports,
    store_votes,
)
from app.schemas import (
    Persona,
    EducationLevel,
    EvaluateResponse,
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
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return row[0]


def test_persist_writes_one_row_per_persona(conn):
    persist_persona(conn, make_persona())

    assert _count(conn, "personas") == 1


def test_persist_is_idempotent_on_rerun(conn):
    assert persist_persona(conn, make_persona()) is True
    assert persist_persona(conn, make_persona()) is False

    assert _count(conn, "personas") == 1


def test_apply_schema_is_idempotent(conn):
    apply_schema(conn)
    apply_schema(conn)


def test_every_table_the_schema_declares_is_parsed_out_of_it() -> None:
    """The probe reads its table list out of `schema.sql` (115/#248), which
    makes the parser the single point of failure: a reformat the regex stops
    matching would leave `apply_schema` probing nothing at all, silently, and
    the protection this ticket adds would evaporate with no test to notice.

    Counted a second way — by counting the `CREATE TABLE` lines — so the claim
    does not rest on the same reading twice.
    """
    schema = (Path(app.persistence.__file__).parent / "schema.sql").read_text()
    parsed = schema_columns()
    # A second reading rather than the same one: whole lines, not regex-matched
    # bodies. Comment lines are dropped because the file documents its own DDL
    # in prose — this counts statements, not occurrences of the phrase.
    declared = sum(
        line.startswith("CREATE TABLE IF NOT EXISTS") for line in schema.splitlines()
    )

    assert declared > 0, "schema.sql declares no tables — read the wrong file?"
    assert len(parsed) == declared
    for table, columns in parsed.items():
        assert columns, f"{table} parsed with no columns"


_ADDITIVE = """
CREATE TABLE IF NOT EXISTS votes (
    request_fingerprint text PRIMARY KEY,
    reason              text NOT NULL
);

ALTER TABLE votes ADD COLUMN IF NOT EXISTS scored_at timestamptz;
"""


def test_ddl_the_parser_refuses_is_refused_before_it_is_applied(conn, monkeypatch):
    """The order the guard has to run in (115/#248, review).

    Refusing a bare `ADD COLUMN` *after* `conn.execute(_SCHEMA_SQL)` has already
    committed it reports a problem the check itself caused, and the second run
    then dies on `DuplicateColumn` — which the curated handler does not catch,
    so the operator gets a raw traceback and the RLS sweep never runs. The
    parse is a pure function of the file, so it costs nothing to do first.
    """
    monkeypatch.setattr(
        app.persistence,
        "_SCHEMA_SQL",
        "CREATE TABLE IF NOT EXISTS drift_probe (id text PRIMARY KEY\n);\n"
        "ALTER TABLE drift_probe ADD COLUMN scored_at timestamptz;\n",
    )
    try:
        with pytest.raises(ValueError, match="IF NOT EXISTS"):
            apply_schema(conn)

        landed = conn.execute(
            "SELECT to_regclass('public.drift_probe') IS NOT NULL"
        ).fetchone()
        assert landed is not None and landed[0] is False, (
            "the refused DDL was applied before being refused"
        )
    finally:
        conn.execute("DROP TABLE IF EXISTS drift_probe")
        conn.commit()


@pytest.mark.parametrize(
    "statement",
    [
        # Postgres makes COLUMN optional, so this is a legal addition.
        "ALTER TABLE votes ADD scored_at timestamptz;",
        # And the `IF EXISTS` guard on the table is legal too.
        "ALTER TABLE IF EXISTS votes ADD COLUMN scored_at timestamptz;",
        "ALTER TABLE votes ADD COLUMN scored_at timestamptz;",
    ],
)
def test_an_addition_the_parser_does_not_understand_is_refused(statement) -> None:
    """Recognising one spelling is not enforcing a form (115/#248, review).

    Both alternative spellings are legal SQL that Postgres would apply, and
    both used to parse to nothing at all: no `IF NOT EXISTS` complaint *and*
    the new column never reached the probe list — so a column could go missing
    on a deployed database undetected, which is the failure this parser exists
    to remove. Anything but the documented form is refused.
    """
    with pytest.raises(ValueError, match="ALTER TABLE"):
        schema_columns(
            "CREATE TABLE IF NOT EXISTS votes (id text PRIMARY KEY\n);\n" + statement
        )


def test_a_documented_drop_is_read_and_the_column_leaves_the_probe() -> None:
    """084/#175 widened the parser by one exact spelling. The dropped column must
    not be probed for — probing would report a current database as stale — and
    nothing else about the table changes."""
    parsed = schema_columns(
        "CREATE TABLE IF NOT EXISTS personas (\n    id text PRIMARY KEY,\n"
        "    age integer NOT NULL\n);\n"
        "ALTER TABLE personas DROP COLUMN IF EXISTS summary_embedding;"
    )

    assert parsed == {"personas": ("id", "age")}


@pytest.mark.parametrize("table", ["votes", "tests", "request_ledger"])
def test_a_drop_on_a_table_that_cannot_be_rebuilt_is_refused(table) -> None:
    """Half of the drop rule in code rather than prose (084/#175, security
    review): a column may go only if its contents are regenerable, and
    `_REGENERABLE` already names the tables that are — `personas` and the
    corpus. `votes` is paid model output; the ledgers hold spend nobody has been
    charged for yet. A drop on any of them is refused before it lands, however
    well-formed the statement."""
    with pytest.raises(ValueError, match="_REGENERABLE"):
        schema_columns(
            f"CREATE TABLE IF NOT EXISTS {table} (\n    id text PRIMARY KEY,\n"
            f"    reason text\n);\n"
            f"ALTER TABLE {table} DROP COLUMN IF EXISTS reason;"
        )


def test_a_drop_wins_over_a_create_that_still_lists_the_column() -> None:
    """The transitional mistake: the DROP is added below but the column is left
    in the CREATE TABLE above. `apply_schema` would drop it and then probe for
    it, reporting a database that applied this very file as stale. The drop has
    to take the column off the probe whatever the CREATE says — found by a
    mutation check that replaced the removal with `pass` and turned nothing red."""
    parsed = schema_columns(
        "CREATE TABLE IF NOT EXISTS personas (\n    id text PRIMARY KEY,\n"
        "    summary_embedding vector(1536) NOT NULL\n);\n"
        "ALTER TABLE personas DROP COLUMN IF EXISTS summary_embedding;"
    )

    assert parsed == {"personas": ("id",)}


@pytest.mark.parametrize(
    "statement",
    [
        # A drop without the guard fails forever after the first apply, the
        # same mid-file failure the ADD form's IF NOT EXISTS exists to prevent.
        "ALTER TABLE personas DROP COLUMN summary_embedding;",
        # The two changes the policy still forbids outright.
        "ALTER TABLE personas RENAME COLUMN age TO years;",
        "ALTER TABLE personas ALTER COLUMN age TYPE bigint;",
        # Legal Postgres, undocumented spelling — refused like the ADD variants.
        "ALTER TABLE personas DROP summary_embedding;",
    ],
)
def test_a_change_the_policy_forbids_or_the_parser_cannot_read_is_refused(
    statement,
) -> None:
    """Widening by one spelling is not loosening: everything that is not the
    ADD form or the DROP form is still refused before it lands."""
    with pytest.raises(ValueError, match="ALTER TABLE"):
        schema_columns(
            "CREATE TABLE IF NOT EXISTS personas (\n    id text PRIMARY KEY\n);\n"
            + statement
        )


def _persona_vector_state(conn) -> tuple[bool, bool]:
    column = conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = 'personas'"
        " AND column_name = 'summary_embedding'"
    ).fetchone()
    index = conn.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'personas_summary_embedding_idx'"
    ).fetchone()
    return column is not None, index is not None


def test_applying_the_schema_to_a_database_that_still_has_the_persona_vector_drops_it(
    conn,
):
    """The deploy's own path (084/#175): the live database was seeded when
    `personas.summary_embedding` and its HNSW index existed. Running
    `--schema-only` there must remove both, converge on a second run, and never
    create them on a fresh database — `IF EXISTS` on both statements is what
    makes one file serve all three cases."""
    conn.execute(
        "ALTER TABLE personas ADD COLUMN IF NOT EXISTS summary_embedding vector(1536)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS personas_summary_embedding_idx"
        " ON personas USING hnsw (summary_embedding vector_cosine_ops)"
    )
    conn.commit()
    assert _persona_vector_state(conn) == (True, True), "legacy state not set up"

    apply_schema(conn)
    assert _persona_vector_state(conn) == (False, False)

    apply_schema(conn)  # idempotent: nothing to drop is not an error
    assert _persona_vector_state(conn) == (False, False)


def test_a_column_spelling_the_parser_cannot_read_is_refused() -> None:
    """A quoted or all-caps column name was dropped silently, which is a column
    that exists in the table and is never probed — the exact blindness this
    parser replaced. Refused rather than skipped, since a parser that guesses
    is a probe that lies."""
    with pytest.raises(ValueError, match="order"):
        schema_columns(
            'CREATE TABLE IF NOT EXISTS t (\n    "order" text NOT NULL,\n'
            "    id text PRIMARY KEY\n);"
        )


def test_a_stale_schema_that_the_catalogue_cannot_explain_still_says_why(
    conn, monkeypatch
):
    """The error path must never be empty (115/#248, review).

    `schema.sql` can fail with `UndefinedColumn` over a column the parser never
    learned about — an index referencing one, with no `ALTER` declaring it. The
    catalogue then reports nothing missing, and the message named nothing and
    offered no remedy: "missing a column this build writes — ." The old
    hardcoded tuple at least named itself, so an empty message is a regression.
    """
    monkeypatch.setattr(
        app.persistence,
        "_SCHEMA_SQL",
        "CREATE TABLE IF NOT EXISTS drift_probe (id text PRIMARY KEY\n);\n"
        "CREATE INDEX IF NOT EXISTS drift_probe_idx ON drift_probe (scored_at);\n",
    )
    try:
        with pytest.raises(RuntimeError) as failure:
            apply_schema(conn)

        message = str(failure.value)
        assert "scored_at" in message, message
        assert "— ." not in message, "the message named nothing"
    finally:
        conn.execute("DROP TABLE IF EXISTS drift_probe")
        conn.commit()


def test_the_drift_check_needs_select_and_not_only_connect(conn, pg_url) -> None:
    """What grant the CI credential actually needs (115/#248).

    `information_schema.columns` is privilege-filtered: it shows a role only the
    columns that role may read. So a credential granted `USAGE` alone — the
    intuitive "it only reads the catalogue" answer — sees *nothing*, and the
    check reports every table as missing: a red build on a current database.
    `SELECT` on the tables is the minimum that works, and it is still far less
    than the owner credential the deploy notes used to point at.

    The connection is rebuilt from the container's own parts rather than by
    string-substituting the URL. The substitution version passed locally and
    failed in CI, and the reason is worse than the failure: where the pattern
    did not match it connected as the *owner* and asserted nothing at all. So
    `current_user` is checked first — a privilege test that quietly runs as
    superuser is the shape of bug this whole ticket is about.
    """
    apply_schema(conn)
    dsn = urlsplit(pg_url)
    conn.execute("DROP ROLE IF EXISTS drift_check")
    conn.execute("CREATE ROLE drift_check LOGIN PASSWORD 'probe'")
    conn.execute("GRANT USAGE ON SCHEMA public TO drift_check")
    conn.commit()

    def as_role() -> psycopg.Connection:
        return psycopg.connect(
            host=dsn.hostname,
            port=dsn.port,
            dbname=dsn.path.lstrip("/"),
            user="drift_check",
            password="probe",
        )

    try:
        with as_role() as probe:
            who = probe.execute("SELECT current_user").fetchone()
            assert who is not None and who[0] == "drift_check"
            blind = missing_columns(probe)

        assert set(blind) == set(schema_columns()), (
            "USAGE alone should see no columns — if this fails, the grant "
            "documented for CI is stricter than it needs to be"
        )

        conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO drift_check")
        conn.commit()
        with as_role() as probe:
            assert missing_columns(probe) == {}
    finally:
        conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM drift_check")
        conn.execute("REVOKE ALL ON SCHEMA public FROM drift_check")
        conn.execute("DROP ROLE IF EXISTS drift_check")
        conn.commit()


def test_a_column_added_by_alter_is_a_column_the_probe_asks_for() -> None:
    """Additive DDL is the strategy `votes` depends on (083/#173), and a column
    it adds has to reach the probe — a parser reading only `CREATE TABLE`
    bodies would be blind to exactly the columns the strategy exists to add,
    which is the same hole one layer along (115/#248).
    """
    assert schema_columns(_ADDITIVE)["votes"] == (
        "request_fingerprint",
        "reason",
        "scored_at",
    )


def test_a_commented_out_statement_is_documentation_and_not_ddl() -> None:
    """Reproduced on the real file: `schema.sql` documents the additive form by
    showing an `ALTER TABLE … ADD COLUMN IF NOT EXISTS scored_at`, and the
    parser read the example, so the probe demanded a column no table has and
    `apply_schema` refused a perfectly current database (115/#248).
    """
    parsed = schema_columns(
        "CREATE TABLE IF NOT EXISTS votes (id text PRIMARY KEY\n);\n"
        "-- ALTER TABLE votes ADD COLUMN IF NOT EXISTS scored_at timestamptz;\n"
        "--     ALTER TABLE votes ADD COLUMN scored_at timestamptz;\n"
    )

    assert parsed == {"votes": ("id",)}


def test_an_addition_that_could_not_be_re_run_is_refused() -> None:
    """`schema.sql` runs on every seed and every boot, so a bare `ADD COLUMN`
    fails the second time and takes the RLS sweep after it down. The form is
    enforced here rather than asked for in a comment, because the last
    convention this file carried in a comment — "extend this whenever a column
    is added" — was never extended.
    """
    with pytest.raises(ValueError, match="IF NOT EXISTS"):
        schema_columns("ALTER TABLE votes ADD COLUMN scored_at timestamptz;")


def test_a_column_added_to_a_table_nobody_declares_is_refused() -> None:
    """A typo in the table name would otherwise create a phantom entry, and the
    probe would then `SELECT` from a table that does not exist — reporting a
    stale schema on a database that is perfectly current."""
    with pytest.raises(ValueError, match="vote"):
        schema_columns(
            "CREATE TABLE IF NOT EXISTS votes (id text PRIMARY KEY\n);\n"
            "ALTER TABLE vote ADD COLUMN IF NOT EXISTS scored_at timestamptz;"
        )


def test_the_probe_and_the_persona_writer_read_the_same_columns(conn) -> None:
    """`_PERSONA_COLUMNS` is what the INSERT names; the probe is what a stale
    table is measured against. Two lists of one table's columns, so this pins
    that the probe is a superset — a column the writer writes but the probe
    never asks for is a column that can go missing undetected, which is the
    whole failure mode.
    """
    apply_schema(conn)

    written = {name.strip() for name in _PERSONA_COLUMNS.split(",")}

    assert written <= set(schema_columns()["personas"])
    # And the database really has them: the parse is only worth something if the
    # names it produces are the names Postgres knows.
    assert missing_columns(conn) == {}


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


@pytest.mark.parametrize(
    "table, column",
    [
        ("votes", "test_id"),
        ("request_ledger", "caller"),
        ("spend_ledger", "usd"),
        ("corpus_chunks", "passage"),
    ],
)
def test_apply_schema_refuses_a_stale_table_that_is_not_personas(conn, table, column):
    """The probe read one table of the five the build writes, and its own
    comment said to extend it — with nowhere to extend it to (115/#248).

    A ledger missing a column is not a seed-time inconvenience: the seed never
    touches the ledgers, so the first notice is a 500 on a paying request.
    Parametrised over the four unprobed tables rather than asserting one, since
    the point is that no table is exempt.
    """
    conn.execute(f"ALTER TABLE {table} DROP COLUMN {column} CASCADE")
    conn.commit()
    try:
        with pytest.raises(RuntimeError, match=f"{table}.*{column}"):
            apply_schema(conn)
    finally:
        # The container is module-scoped, so the table goes back as schema.sql
        # builds it — `CREATE TABLE IF NOT EXISTS` cannot restore a column.
        conn.execute(f"DROP TABLE {table} CASCADE")
        conn.commit()
        apply_schema(conn)


def test_persist_commits_per_persona_on_an_autocommit_connection(pg_url):
    # the seed CLI's connection mode: each persisted persona must be durable
    # (visible to another connection) immediately, so an interrupted run keeps
    # everything already written. On a non-autocommit connection the per-persona
    # transaction would silently be a savepoint in one run-long transaction.
    with psycopg.connect(pg_url, autocommit=True) as writer:
        prepare_connection(writer)
        writer.execute("TRUNCATE personas CASCADE")
        persist_persona(writer, make_persona())
        with psycopg.connect(pg_url) as reader:
            assert _count(reader, "personas") == 1


def test_persist_pool_writes_all_and_returns_count(conn):
    pool = [
        make_persona(id_="US-00000"),
        make_persona(id_="US-00001"),
    ]

    assert persist_pool(conn, iter(pool)) == 2
    assert _count(conn, "personas") == 2


def test_persist_pool_counts_only_new_writes_on_rerun(conn):
    pool = [
        make_persona(id_="US-00000"),
        make_persona(id_="US-00001"),
    ]

    assert persist_pool(conn, pool) == 2
    assert persist_pool(conn, pool) == 0
    assert _count(conn, "personas") == 2


# The whole pool, unfiltered — every retrieval test narrows this rather than
# assembling eight fields, so what each one is actually about stays visible.
_EVERYONE = resolve_target(TargetRequest())

# An age span nobody can fall in — what "under 18" clamps to.
_NOBODY = _EVERYONE.model_copy(update={"min_age": 18, "max_age": 17})


@pytest.mark.anyio
async def test_retrieval_filters_on_country(conn, aconn):
    persist_pool(
        conn,
        [
            make_persona(id_="US-00000", country="US"),
            make_persona(id_="JP-00000", country="JP"),
        ],
    )

    panel = await retrieve_panel(
        aconn, _EVERYONE.model_copy(update={"countries": (Locale.JP,)}), size=10, seed=0
    )

    assert [p.id for p in panel] == ["JP-00000"]


@pytest.mark.anyio
async def test_no_coverage_retrieves_nobody(conn, aconn):
    """An empty `countries` is the ladder's bottom rung, not a missing filter. The
    dangerous failure would be reading it as "no country constraint" and returning a
    random panel that looks like a matched one."""
    persist_pool(conn, [make_persona(id_="US-00000")])

    assert (
        await retrieve_panel(
            aconn, _EVERYONE.model_copy(update={"countries": ()}), size=10, seed=0
        )
        == []
    )


@pytest.mark.anyio
async def test_retrieval_filters_on_the_age_span(conn, aconn):
    persist_pool(
        conn,
        [
            make_persona(id_="US-00000", age=29),
            make_persona(id_="US-00001", age=30),
            make_persona(id_="US-00002", age=39),
            make_persona(id_="US-00003", age=40),
        ],
    )

    panel = await retrieve_panel(
        aconn,
        _EVERYONE.model_copy(update={"min_age": 30, "max_age": 39}),
        size=10,
        seed=0,
    )

    assert sorted(p.age for p in panel) == [30, 39]


@pytest.mark.anyio
async def test_an_inverted_age_span_retrieves_nobody(conn, aconn):
    """What "under 18" clamps to. It has to match nobody rather than everybody."""
    persist_pool(conn, [make_persona(id_="US-00000", age=34)])

    panel = await retrieve_panel(
        aconn,
        _EVERYONE.model_copy(update={"min_age": 18, "max_age": 17}),
        size=10,
        seed=0,
    )

    assert panel == []


@pytest.mark.anyio
async def test_retrieval_filters_on_gender_income_and_education(conn, aconn):
    wanted = make_persona(
        id_="US-00000", gender="male", income_quintile=5, education="secondary"
    )
    persist_pool(
        conn,
        [
            wanted,
            make_persona(id_="US-00001", gender="female"),
            make_persona(id_="US-00002", gender="male", income_quintile=1),
            make_persona(
                id_="US-00003",
                gender="male",
                income_quintile=5,
                education="tertiary",
            ),
        ],
    )

    panel = await retrieve_panel(
        aconn,
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


def _with_trait(trait: TraitName, score: float, id_: str) -> Persona:
    return make_persona(id_=id_, big_five=big_five(**{trait: score}))


def _requesting(trait: TraitName, level: TraitLevel) -> TargetQuery:
    return _EVERYONE.model_copy(
        update={
            "traits": (TraitRequest(trait=trait, level=level, source_phrase="stub"),)
        }
    )


@pytest.mark.anyio
async def test_a_requested_trait_level_filters_rather_than_ranks(conn, aconn):
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

    panel = await retrieve_panel(
        aconn, _requesting("neuroticism", TraitLevel.HIGH), size=10, seed=0
    )

    assert [p.id for p in panel] == ["US-00000"]


@pytest.mark.anyio
async def test_a_requested_level_admits_the_levels_beyond_it(conn, aconn):
    """Asking for cautious people must not exclude the most cautious of them, so a
    `very_high` score is inside `high`'s bound rather than past it."""
    persist_pool(
        conn,
        [
            _with_trait("openness", 1.0, "US-00000"),  # high
            _with_trait("openness", 2.5, "US-00001"),  # very_high
        ],
    )

    panel = await retrieve_panel(
        aconn, _requesting("openness", TraitLevel.HIGH), size=10, seed=0
    )

    assert [p.id for p in panel] == ["US-00000", "US-00001"]


@pytest.mark.anyio
async def test_a_requested_middle_level_excludes_both_tails(conn, aconn):
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

    panel = await retrieve_panel(
        aconn, _requesting("extraversion", TraitLevel.MEDIUM), size=10, seed=0
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
@pytest.mark.anyio
async def test_a_score_on_a_boundary_matches_the_level_it_renders_as(
    conn, aconn, score, admits, refuses
):
    """The one thing a Python check of the bounds cannot establish: that Postgres
    compares them the way the table means. Every boundary belongs to the inner band, so
    the level a score renders as must admit it and the level beyond must refuse it —
    and these four scores are where a `>` written as `>=` on either side would show.
    """
    persist_pool(conn, [_with_trait("openness", score, "US-00000")])

    assert await retrieve_panel(aconn, _requesting("openness", admits), size=10, seed=0)
    assert (
        await retrieve_panel(aconn, _requesting("openness", refuses), size=10, seed=0)
        == []
    )


@pytest.mark.anyio
async def test_two_requested_traits_both_have_to_match(conn, aconn):
    """Each trait multiplies the filter, which is where a thin panel comes from —
    reporting that is the caller's job, so retrieval only has to be exact."""
    persist_pool(
        conn,
        [
            make_persona(
                id_="US-00000",
                big_five=big_five(openness=1.0, neuroticism=-1.0),
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

    assert [p.id for p in await retrieve_panel(aconn, query, size=10, seed=0)] == [
        "US-00000"
    ]


@pytest.mark.anyio
async def test_a_trait_filter_still_draws_a_sample_rather_than_a_ranking(conn, aconn):
    """Nothing is ranked, so the seed reaches a target that names a temperament too.
    That is what makes two independent draws of one target possible, and with them the
    sample-stability check."""
    persist_pool(
        conn,
        [_with_trait("openness", 1.0, f"US-{i:05d}") for i in range(10)],
    )
    query = _requesting("openness", TraitLevel.HIGH)

    drawn = {
        tuple(p.id for p in await retrieve_panel(aconn, query, size=4, seed=seed))
        for seed in range(5)
    }

    assert len(drawn) > 1


def _numbered_pool(conn: psycopg.Connection, count: int) -> None:
    persist_pool(
        conn,
        list(make_persona(id_=f"US-{i:05d}") for i in range(count)),
    )


@pytest.mark.anyio
async def test_a_target_with_no_disposition_draws_a_reproducible_sample(conn, aconn):
    _numbered_pool(conn, 10)

    first = [p.id for p in await retrieve_panel(aconn, _EVERYONE, size=4, seed=7)]
    again = [p.id for p in await retrieve_panel(aconn, _EVERYONE, size=4, seed=7)]

    assert first == again
    assert len(first) == 4


@pytest.mark.anyio
async def test_the_seed_chooses_who_is_sampled(conn, aconn):
    """Reproducible must not mean fixed: two tests of the same target should be able
    to draw different panels, which is what makes sample-stability measurable."""
    _numbered_pool(conn, 10)

    drawn = {
        tuple(p.id for p in await retrieve_panel(aconn, _EVERYONE, size=4, seed=seed))
        for seed in range(5)
    }

    assert len(drawn) > 1
    # and it is a sample, not the first four ids in a different order
    assert drawn != {tuple(f"US-{i:05d}" for i in range(4))}


@pytest.mark.anyio
async def test_a_panel_larger_than_the_pool_returns_what_exists(conn, aconn):
    """Which is what makes the shortfall reportable rather than an error."""
    _numbered_pool(conn, 3)

    assert len(await retrieve_panel(aconn, _EVERYONE, size=200, seed=0)) == 3


@pytest.mark.anyio
async def test_a_panel_size_below_one_is_rejected(conn, aconn):
    with pytest.raises(ValueError):
        await retrieve_panel(aconn, _EVERYONE, size=0, seed=0)


@pytest.mark.anyio
async def test_size_caps_the_panel(conn, aconn):
    _numbered_pool(conn, 10)

    assert len(await retrieve_panel(aconn, _EVERYONE, size=4, seed=0)) == 4


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


@pytest.mark.anyio
async def test_a_stored_vote_loads_back_whole(conn, aconn):
    record = _vote_record()
    assert await store_votes(aconn, {"fp1": record}, owner="acct-a") == 1

    assert await load_votes(aconn, ["fp1"], owner="acct-a") == {"fp1": record}


@pytest.mark.anyio
async def test_load_returns_only_the_fingerprints_that_exist(conn, aconn):
    await store_votes(aconn, {"fp1": _vote_record()}, owner="acct-a")

    loaded = await load_votes(aconn, ["fp1", "fp-unknown"], owner="acct-a")
    assert loaded.keys() == {"fp1"}
    assert await load_votes(aconn, [], owner="acct-a") == {}


@pytest.mark.anyio
async def test_the_ledger_is_append_only(conn, aconn):
    """Votes are paid model output — the one table not regenerable from a seed
    by the ledger's append-only rule. A colliding write must leave the original
    untouched, never
    replace it: the first vote under a fingerprint is THE vote for that question."""
    await store_votes(aconn, {"fp1": _vote_record(reason="first")}, owner="acct-a")

    assert (
        await store_votes(aconn, {"fp1": _vote_record(reason="second")}, owner="acct-a")
        == 0
    )
    assert (await load_votes(aconn, ["fp1"], owner="acct-a"))["fp1"].reason == "first"


@pytest.mark.anyio
async def test_votes_load_only_for_their_owner(conn, aconn):
    """086/#177: the ledger is a user-scoped resume buffer, not a shared cache.
    A row's content is its owner's submitted headlines, so the read matches
    within the owner or not at all — privacy by the WHERE clause, not by
    policy."""
    await store_votes(aconn, {"fp1": _vote_record()}, owner="acct-a")

    assert await load_votes(aconn, ["fp1"], owner="acct-b") == {}
    assert (await load_votes(aconn, ["fp1"], owner="acct-a")).keys() == {"fp1"}


@pytest.mark.anyio
async def test_a_colliding_write_never_reassigns_the_owner(conn, aconn):
    """Two accounts submitting byte-identical content collide on the ledger's
    primary key. Append-only already settles it: the first row stands, still
    its first owner's, and the second account simply has no row — it paid for
    its own votes and will pay again on a resume. Accepted with the scoping
    (086/#177): holding both rows means dropping the primary key for a
    composite one, which the additive-only migration rule (083/#173) refuses
    and the ticket's own "same ON CONFLICT DO NOTHING" declined."""
    await store_votes(aconn, {"fp1": _vote_record(reason="first")}, owner="acct-a")

    assert (
        await store_votes(aconn, {"fp1": _vote_record(reason="second")}, owner="acct-b")
        == 0
    )
    assert await load_votes(aconn, ["fp1"], owner="acct-b") == {}
    assert (await load_votes(aconn, ["fp1"], owner="acct-a"))["fp1"].reason == "first"


@pytest.mark.anyio
async def test_the_empty_owner_is_refused_loudly(conn, aconn):
    """'' is the column DEFAULT — the mark of rows written before the column
    existed, or by an older deploy mid-rollout. No live caller is ever that:
    a request that lost its identity must fail before it writes rows nobody
    can read back, or reads the pre-scoping pool."""
    with pytest.raises(ValueError):
        await store_votes(aconn, {"fp1": _vote_record()}, owner="")
    with pytest.raises(ValueError):
        await load_votes(aconn, ["fp1"], owner="")


@pytest.mark.anyio
async def test_rows_from_before_the_scoping_are_readable_by_no_account(conn, aconn):
    """A pre-086 row lands on the DEFAULT '' when the column arrives. It stays
    — paid model output is never dropped by a migration — but no signed-in
    account matches it: the sharing the scoping kills is killed for the old
    rows too, not only for new writes."""
    await aconn.execute(
        "INSERT INTO votes (request_fingerprint, persona_id, test_id,"
        " chosen_variant_id, presentation_order, reason)"
        " VALUES ('fp-old', 'JP-00001', 't0', 'a', ARRAY['a','b'], 'legacy')"
    )
    await aconn.commit()

    assert await load_votes(aconn, ["fp-old"], owner="acct-a") == {}
    owner = await (
        await aconn.execute(
            "SELECT owner_id FROM votes WHERE request_fingerprint = 'fp-old'"
        )
    ).fetchone()
    assert owner == ("",)


@pytest.mark.anyio
async def test_count_reports_excludes_the_test_being_kept(conn, aconn):
    """The save cap must not scold a re-completed run for a row it is not
    adding: counting excludes the test's own id, so an already-kept test
    re-stores as the idempotent no-op it always was (085/#176)."""
    await store_report(aconn, test_id="t-1", owner="acct-a", report={"x": 1})
    await store_report(aconn, test_id="t-2", owner="acct-b", report={"x": 1})

    assert await count_reports(aconn, owner="acct-a", excluding="t-1") == 0
    assert await count_reports(aconn, owner="acct-a", excluding="t-other") == 1
    # Another account's rows never count against this one.
    assert await count_reports(aconn, owner="acct-b", excluding="t-other") == 1


def test_every_table_denies_the_data_api_by_default(conn) -> None:
    """Row-level security on, with no policies, on everything in `public`.

    063/#158 ships a Supabase publishable key to the browser, and that key
    reaches the project's Data API — which serves whatever `public` holds
    unless row-level security says otherwise. RLS with no policy denies every
    role that goes through it, while the tables' owner (the role this backend
    connects as) bypasses it, so the app is unaffected and the REST surface is
    empty.

    Asserted over the whole schema rather than a list, so a table added later
    is covered the day it appears rather than the day someone remembers.
    """
    apply_schema(conn)
    # A stand-in for a table the checkpointer library creates after us: the
    # sweep must reach tables this file never mentions.
    conn.execute("CREATE TABLE IF NOT EXISTS latecomer (id int)")
    conn.commit()

    deny_data_api(conn)

    unprotected = conn.execute(
        "SELECT relname FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relkind = 'r'"
        " AND NOT c.relrowsecurity"
    ).fetchall()
    assert unprotected == []


def test_the_owner_can_still_read_what_it_protected(conn) -> None:
    """RLS that also locked out the application would be a outage, not a
    control. Postgres exempts a table's owner unless FORCE is asked for, and
    this backend connects as the owner."""
    apply_schema(conn)
    deny_data_api(conn)

    persist_pool(conn, [make_persona()])

    assert len(load_pool(conn)) == 1


def test_the_sweep_works_on_the_autocommit_connection_startup_uses(pg_url) -> None:
    """The checkpointer's pool is autocommit (main.lifespan), and that is the
    connection the startup sweep borrows — so the sweep must not assume a
    transaction it can commit."""
    with psycopg.connect(pg_url, autocommit=True) as conn:
        apply_schema(conn)

        deny_data_api(conn)

        unprotected = conn.execute(
            "SELECT relname FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = 'public' AND c.relkind = 'r'"
            " AND NOT c.relrowsecurity"
        ).fetchall()
    assert unprotected == []


# --- The tests table (117/#252) ----------------------------------------------


@pytest.mark.anyio
async def test_a_stored_report_loads_back_as_the_model_that_wrote_it(conn, aconn):
    """The whole `EvaluateResponse` travels as JSONB, so what comes back has to
    validate as one. A row read as a plain dict would let a field quietly change
    type between write and read and only fail at render, in front of the
    customer whose report it is."""
    report = make_report()

    await store_report(aconn, test_id="t-1", owner="person-1", report=report)

    loaded = await load_report(aconn, test_id="t-1", owner="person-1")
    assert loaded is not None
    assert EvaluateResponse.model_validate(loaded).model_dump(mode="json") == report


@pytest.mark.anyio
async def test_a_report_is_not_readable_by_anyone_else(conn, aconn):
    """A test id is not a credential — the rule `/evaluate/resume` already
    applies to a thread id. Enforced in the query rather than by a check after
    the read, so there is no path where the row is in memory before ownership
    has been decided."""
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())

    assert await load_report(aconn, test_id="t-1", owner="somebody-else") is None
    assert await delete_report(aconn, test_id="t-1", owner="somebody-else") is False
    assert await load_report(aconn, test_id="t-1", owner="person-1") is not None


@pytest.mark.anyio
async def test_the_listing_is_newest_first_and_one_owners_only(conn, aconn):
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())
    await store_report(aconn, test_id="t-2", owner="person-1", report=make_report())
    await store_report(aconn, test_id="t-3", owner="person-2", report=make_report())

    listed = await list_reports(aconn, owner="person-1", limit=10)

    assert [row["test_id"] for row in listed] == ["t-2", "t-1"]
    assert all(row["created_at"] is not None for row in listed)


@pytest.mark.anyio
async def test_the_listing_carries_the_headlines_and_never_the_whole_report(
    conn, aconn
):
    """The sidebar renders `"A" vs "B"` and a verdict phrase, and searches on
    the two headlines — so the listing needs them, and needs nothing else. A
    listing that returned whole reports would load every one of a customer's
    tests to draw a rail of labels."""
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())

    row = (await list_reports(aconn, owner="person-1", limit=10))[0]

    assert row["variants"] == {"a": "Save 50% today", "b": "Limited time: half price"}
    assert "report" not in row, "the listing loaded the whole document"


@pytest.mark.anyio
async def test_a_deleted_report_is_gone_rather_than_hidden(conn, aconn):
    """ "Delete must actually delete" — the prototype's own words about this
    rail. A soft delete would leave the customer's headline text in a table
    they asked to be rid of."""
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())

    assert await delete_report(aconn, test_id="t-1", owner="person-1") is True

    assert await load_report(aconn, test_id="t-1", owner="person-1") is None
    remaining = await (await aconn.execute("SELECT count(*) FROM tests")).fetchone()
    assert remaining is not None and remaining[0] == 0
    # Deleting what is not there is not an error, so a double-click is not a 500.
    assert await delete_report(aconn, test_id="t-1", owner="person-1") is False


@pytest.mark.anyio
async def test_deleting_an_account_takes_its_reports_with_it(conn, aconn):
    """The finding that made this more than "add a table" (117/#252): a report
    holds the customer's headline text and the phrases their audience reading
    quoted, so `DELETE /me`'s reasoning — that what stays behind is "not
    personal data once the account is gone" — stops being true here."""
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())
    await store_report(aconn, test_id="t-2", owner="person-2", report=make_report())

    assert await delete_reports_of(aconn, owner="person-1") == 1

    assert await list_reports(aconn, owner="person-1", limit=10) == []
    assert len(await list_reports(aconn, owner="person-2", limit=10)) == 1


@pytest.mark.anyio
async def test_storing_the_same_run_twice_leaves_the_first_report(conn, aconn):
    """A resumed or retried run must not rewrite a report the customer may
    already be reading. Same rule as the votes ledger, for a weaker reason: the
    report is derived rather than paid for, but a report that changes under a
    reader is worse than one that is merely stale."""
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())
    second = make_report(variants={"a": "rewritten", "b": "also rewritten"})

    await store_report(aconn, test_id="t-1", owner="person-1", report=second)

    loaded = await load_report(aconn, test_id="t-1", owner="person-1")
    assert loaded is not None and loaded["variants"]["a"] == "Save 50% today"


@pytest.mark.anyio
async def test_a_report_this_build_cannot_render_is_invisible(conn, aconn):
    """Why `schema_version` is a column rather than a comment. A row written by
    a future build is not listed and not loaded, because showing a customer a
    report drawn from a document this code no longer understands is worse than
    not showing it. Account deletion still takes it — see below."""
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())
    await aconn.execute(
        "UPDATE tests SET schema_version = %s", (REPORT_SCHEMA_VERSION + 1,)
    )

    assert await load_report(aconn, test_id="t-1", owner="person-1") is None
    assert await list_reports(aconn, owner="person-1", limit=10) == []
    # Unrenderable is still the customer's content, so "delete my account" must
    # empty the table rather than the readable part of it.
    assert await delete_reports_of(aconn, owner="person-1") == 1


@pytest.mark.anyio
async def test_an_unkept_report_is_readable_by_its_owner_but_not_in_the_rail(
    conn, aconn
):
    """The analyst reads the server's copy of every report (035/#136), so a run
    the rail refused under 085's cap is still stored — hidden from the list and
    the count, readable by id under its owner and nobody else."""
    await store_report(aconn, test_id="t-kept", owner="p-1", report=make_report())
    await store_report(
        aconn, test_id="t-over", owner="p-1", report=make_report(), kept=False
    )

    listed = await list_reports(aconn, owner="p-1", limit=10)
    assert [row["test_id"] for row in listed] == ["t-kept"]
    assert await count_reports(aconn, owner="p-1", excluding="t-none") == 1
    assert await load_report(aconn, test_id="t-over", owner="p-1") is not None
    assert await load_report(aconn, test_id="t-over", owner="stranger") is None
    # Hidden is not exempt: the customer's own delete, and "delete my account",
    # take unkept rows with them.
    assert await delete_report(aconn, test_id="t-over", owner="p-1") is True
    await store_report(
        aconn, test_id="t-over-2", owner="p-1", report=make_report(), kept=False
    )
    assert await delete_reports_of(aconn, owner="p-1") == 2


@pytest.mark.anyio
async def test_the_sweep_takes_only_unkept_reports_past_the_horizon(conn, aconn):
    """Unkept rows live for a fixed horizon, then the on-write sweep takes them
    — the spend ledger's own rule. A kept row is the customer's until they
    delete it, however old; a young unkept row may still have a page open on it."""
    for test_id, kept in (("old-kept", True), ("old-over", False), ("new-over", False)):
        await store_report(
            aconn, test_id=test_id, owner="p-1", report=make_report(), kept=kept
        )
    await aconn.execute(
        "UPDATE tests SET created_at = now() - interval '25 hours'"
        " WHERE test_id IN ('old-kept', 'old-over')"
    )
    await aconn.commit()

    assert await sweep_unkept_reports(aconn, older_than_hours=24) == 1

    remaining = await (
        await aconn.execute("SELECT test_id FROM tests ORDER BY test_id")
    ).fetchall()
    assert remaining == [("new-over",), ("old-kept",)]


# 108/#231: the skip path asks this before it charges, so both callers of one
# predicate must agree — and the read must not sit open across the model call
# that follows it on the caller's path.
@pytest.mark.anyio
async def test_the_pool_is_asked_whether_anybody_matches_at_all(conn, aconn):
    _numbered_pool(conn, 3)

    assert await anyone_matches(aconn, _EVERYONE) is True
    assert await anyone_matches(aconn, _NOBODY) is False


@pytest.mark.anyio
async def test_asking_leaves_no_transaction_open(conn, aconn):
    """`_refuse_if_run_capped` states the rule this shares: nothing was
    written, and a pooled connection must not idle in transaction across the
    audience classifier's call."""
    _numbered_pool(conn, 3)

    await anyone_matches(aconn, _EVERYONE)

    assert aconn.info.transaction_status == TransactionStatus.IDLE


@pytest.mark.anyio
async def test_the_answer_agrees_with_what_the_draw_seats(conn, aconn):
    """One predicate, two callers: a target the check clears must seat somebody,
    and one it refuses must seat nobody. This is the drift the extraction was
    for — a check that disagreed with the draw would charge for an empty panel."""
    _numbered_pool(conn, 3)

    for query in (_EVERYONE, _NOBODY):
        drawn = await retrieve_panel(aconn, query, size=10, seed=0)
        assert await anyone_matches(aconn, query) is bool(drawn)


# --- The feedback table (053/#150) --------------------------------------------


@pytest.mark.anyio
async def test_feedback_lands_against_the_readers_own_test(conn, aconn):
    """A row is the reader, the test they were looking at, and what they said;
    the operator's query joins it to the report."""
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())

    stored = await store_feedback(
        aconn, owner="person-1", test_id="t-1", body="I could not tell what to ship."
    )

    assert stored is True
    rows = await (await aconn.execute(FEEDBACK_QUERY)).fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("person-1", "t-1", "I could not tell what to ship.")
    ]


@pytest.mark.anyio
async def test_feedback_on_someone_elses_test_is_refused(conn, aconn):
    """The reference is scoped like every read of `tests`: a test id the caller
    does not own is not theirs to comment on, and the row is not written."""
    await store_report(aconn, test_id="t-1", owner="person-1", report=make_report())

    stored = await store_feedback(
        aconn, owner="person-2", test_id="t-1", body="looks wrong"
    )

    assert stored is False
    assert (await (await aconn.execute(FEEDBACK_QUERY)).fetchall()) == []


@pytest.mark.anyio
async def test_deleting_the_test_deletes_its_feedback(conn, aconn):
    """Decision Q1: feedback lives exactly as long as the test it is about, so
    the customer's delete is a real delete and no copy of their report's
    context survives it — by account or by test."""
    for owner, test_id in (
        ("person-1", "t-1"),
        ("person-1", "t-2"),
        ("person-2", "t-3"),
    ):
        await store_report(aconn, test_id=test_id, owner=owner, report=make_report())
        await store_feedback(aconn, owner=owner, test_id=test_id, body="noted")

    await delete_report(aconn, test_id="t-1", owner="person-1")
    await delete_reports_of(aconn, owner="person-2")

    rows = await (await aconn.execute(FEEDBACK_QUERY)).fetchall()
    assert [r[1] for r in rows] == ["t-2"]
