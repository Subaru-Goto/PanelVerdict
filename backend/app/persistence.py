"""Persist assembled personas to Postgres + pgvector.

The connection is injected (not built from settings) so this is testable against
a throwaway container without live credentials. Idempotent: re-running the seed
skips personas already present.
"""

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Literal, TypedDict, cast

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.assembly import AssembledPersona
from app.bigfive import LEVEL_BOUNDS
from app.schemas import BigFive, Persona, TargetQuery, VoteRecord


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

# Tables whose every row is a pure function of something in git or of the master
# seed, so dropping one loses no information. `votes` is deliberately absent: it
# is paid model output. The ledgers are absent too — their own comments call
# expired rows dead weight, but an unexpired row is a spend nobody has been
# charged for yet, so the remedy is additive DDL rather than a drop.
_REGENERABLE = frozenset({"personas", "corpus_chunks"})


def schema_columns(sql: str | None = None) -> dict[str, tuple[str, ...]]:
    """Every table `schema.sql` builds, and the columns it gives each one.

    Read out of the DDL the build actually applies, rather than kept by hand
    beside it: the previous probe named one table of five and its own comment
    asked the next person to extend it, which nothing enforced (115/#248). A
    list parsed from the source cannot drift from the source.

    Additive `ALTER TABLE … ADD COLUMN` statements are read too, and their form
    is enforced rather than requested — see `_added_columns`.
    """
    # Comment lines go first, and the whole file is stripped rather than each
    # statement: schema.sql documents the additive form by *showing* an ALTER,
    # and an example read as DDL had the probe demanding a column no table has
    # — measured, on this file's own documentation.
    sql = "\n".join(
        line
        for line in (_SCHEMA_SQL if sql is None else sql).splitlines()
        if not line.lstrip().startswith("--")
    )
    tables: dict[str, tuple[str, ...]] = {}
    for table, body in re.findall(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\);", sql, re.DOTALL
    ):
        tables[table] = tuple(_declared_columns(body))
    for table, column in _added_columns(sql):
        if table not in tables:
            raise ValueError(
                f"schema.sql adds {column} to {table}, which no CREATE TABLE in "
                "it declares — a typo here makes the probe SELECT from a table "
                "that does not exist and report a stale schema on a current "
                "database."
            )
        tables[table] += (column,)
    return tables


def _declared_columns(body: str) -> Iterator[str]:
    """The column names in one `CREATE TABLE` body."""
    for line in body.splitlines():
        # Strip the trailing comment before looking for a name, so a `--` note
        # mentioning a word is never read as a column.
        name = line.split("--")[0].strip().split(" ")[0].strip(",")
        # Table-level constraints (`PRIMARY KEY (a, b)`, `UNIQUE (…)`) open with
        # a keyword rather than a column name.
        if name and name.isidentifier() and not name.isupper():
            yield name


def _added_columns(sql: str) -> Iterator[tuple[str, str]]:
    """Every `(table, column)` an `ALTER TABLE … ADD COLUMN` statement adds.

    `IF NOT EXISTS` is required, not preferred: `schema.sql` runs on every seed
    and every boot, so a bare `ADD COLUMN` fails the second time and takes the
    RLS sweep after it down with it. Refused here rather than asked for in a
    comment — the convention this file used to carry as a comment went eight
    months without being followed.
    """
    for table, guard, column in re.findall(
        r"ALTER TABLE\s+(\w+)\s+ADD COLUMN\s+(IF NOT EXISTS\s+)?(\w+)",
        sql,
        re.IGNORECASE,
    ):
        if not guard:
            raise ValueError(
                f"schema.sql adds {table}.{column} without IF NOT EXISTS. The "
                "file runs on every seed and every boot, so the second run "
                "would fail and the RLS sweep after it would not run."
            )
        yield table, column


def apply_schema(conn: psycopg.Connection) -> None:
    """Create the schema if absent (idempotent), then refuse a stale one.

    `CREATE … IF NOT EXISTS` silently accepts an out-of-date table, and the
    resulting failure is invisible rather than loud: a pool seeded before the
    embedding column existed makes every id a resume-skip, so no insert ever
    names the missing column and the run reports "0 written, 200 already
    present" over a pool with no embeddings. On a ledger it is worse — the seed
    never touches those, so the first notice is a 500 on a paying request.

    Every table is probed, because every table can go stale the same way.
    """
    # The index statements reference columns, so on some stale tables schema.sql
    # itself fails before the probe — same cause, same remedy, so both paths
    # land in the one curated error below.
    try:
        conn.execute(_SCHEMA_SQL)
        conn.commit()
    except psycopg.errors.UndefinedColumn as error:
        conn.rollback()
        raise RuntimeError(_stale_schema_message(conn)) from error

    for table, columns in schema_columns().items():
        try:
            conn.execute(f"SELECT {', '.join(columns)} FROM {table} LIMIT 0")
        except psycopg.errors.UndefinedColumn as error:
            conn.rollback()
            raise RuntimeError(_stale_schema_message(conn)) from error


def missing_columns(conn: psycopg.Connection) -> dict[str, tuple[str, ...]]:
    """Which columns `schema.sql` names that the connected database lacks.

    Read from the catalogue in one query rather than by probing, so a caller
    with SELECT and nothing else can ask — which is what the CI drift check
    holds: it must be unable to apply a migration even if it wanted to.
    """
    wanted = schema_columns()
    rows = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = ANY(%s)",
        (list(wanted),),
    ).fetchall()
    present: dict[str, set[str]] = {table: set() for table in wanted}
    for table, column in rows:
        present[table].add(column)
    return {
        table: tuple(column for column in columns if column not in present[table])
        for table, columns in wanted.items()
        if set(columns) - present[table]
    }


def _stale_schema_message(conn: psycopg.Connection) -> str:
    """What to do about a database this build has outgrown.

    Composed rather than written once, because the remedy is not the same for
    every table: a regenerable table can be dropped and rebuilt, and `votes`
    cannot — it is paid model output, so its only remedy is the additive DDL
    `schema.sql` documents. The catalogue says which tables are actually short,
    so the message names them rather than the one the probe happened to reach.
    """
    stale = missing_columns(conn)
    named = ", ".join(
        f"{table} ({', '.join(columns)})" for table, columns in sorted(stale.items())
    )
    remedy = ""
    if droppable := sorted(set(stale) & _REGENERABLE):
        remedy += (
            f"Drop and reseed: {', '.join(droppable)} — every row there is a pure "
            "function of the master seed or of a document in git, so nothing is "
            "lost. "
        )
    if keep := sorted(set(stale) - _REGENERABLE):
        remedy += (
            f"Do not drop {', '.join(keep)} — add the column instead, with the "
            "`ALTER TABLE … ADD COLUMN IF NOT EXISTS` form schema.sql documents. "
        )
    return (
        f"the database is missing a column this build writes — {named}. {remedy}"
        "Never drop the whole database: the votes ledger is paid model output "
        "and cannot be regenerated."
    )


# A lock this sweep waits on is a mistake, not a wait. `ALTER TABLE ... ENABLE
# ROW LEVEL SECURITY` takes ACCESS EXCLUSIVE, and the sweep only fires on the
# boot after a new table appears — i.e. the deploy right after the checkpointer
# migrates its tables, exactly when the outgoing instance may still be holding
# ACCESS SHARE through a multi-minute vote chunk. With no timeout the new
# instance's lifespan waits behind it with nothing served and nothing logged,
# which is the symptom this sweep's own timeout was added to prevent, arriving
# through the next door along. Five seconds is a chosen bound rather than a
# measured one — disclosed, not dressed up — and it matches the figure the test
# fixtures use for the same rule. Timing out fails the boot loudly, which is the
# right outcome: a sweep that did not run leaves transcripts readable.
_LOCK_TIMEOUT = "SET lock_timeout = '5s'"

_DENY_DATA_API = (
    "DO $$ DECLARE t record; BEGIN"
    "  FOR t IN SELECT c.relname FROM pg_class c"
    "    JOIN pg_namespace n ON n.oid = c.relnamespace"
    "    WHERE n.nspname = 'public' AND c.relkind = 'r'"
    "    AND NOT c.relrowsecurity"
    "  LOOP"
    "    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',"
    "                   t.relname);"
    "  END LOOP;"
    "END $$;"
)


def deny_data_api(conn: psycopg.Connection) -> None:
    """Turn row-level security on for every table in `public`, with no policies.

    Supabase serves the whole `public` schema over a REST API that the browser's
    publishable key can reach (063/#158 ships one). A table with RLS off is
    readable there by anyone who visits the site and opens a console; a table
    with RLS on and no policy is readable by nobody who arrives that way, while
    the owner — the role this backend connects as — is exempt unless FORCE is
    asked for, which it is not. So the application is unaffected and the REST
    surface is empty.

    Swept across the schema rather than listed table by table, deliberately:
    the checkpointer creates its own tables from inside the library (#144), and
    those hold analyst transcripts. A list would have to be remembered; a sweep
    covers whatever is there, including tables added after this was written.
    """
    conn.execute(_LOCK_TIMEOUT)
    conn.execute(_DENY_DATA_API)
    conn.commit()


async def adeny_data_api(conn: psycopg.AsyncConnection) -> None:
    """`deny_data_api` for a caller that has an event loop — the lifespan.

    Two implementations of three statements, rather than one shared one: the
    sync version above is the seed's, a script with no loop, and the async
    version lets the lifespan borrow the checkpointer pool's connection instead
    of opening a second one. That borrow is the point. Opening its own
    connection meant a second pooler slot at boot and, worse, a fresh connect on
    the boot path — a deadline to pick where the code this replaced had no
    connect at all and so could not time out.

    The SQL is shared, so the two cannot drift on the part that carries the
    meaning.
    """
    # Reset afterwards: this borrows the checkpointer pool's one connection,
    # which then serves analyst transcripts for the life of the process. A bare
    # `SET` would leave a lock deadline on a subsystem that never asked for one.
    await conn.execute(_LOCK_TIMEOUT)
    try:
        await conn.execute(_DENY_DATA_API)
        await conn.commit()
    finally:
        await conn.execute("RESET lock_timeout")


def prepare_connection(conn: psycopg.Connection) -> None:
    """Ready a connection for the pool: ensure the schema, then register the
    pgvector adapter so vector columns round-trip as numpy arrays. `register_vector`
    needs the extension to exist, so it must follow `apply_schema`.
    """
    apply_schema(conn)
    # Every path that creates these tables also closes them to the Data API —
    # the seed runs from a developer machine against the real project, so a
    # table can exist there long before the app's own startup sweep runs.
    deny_data_api(conn)
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


# The readers pick an ordering, not a SQL fragment. Both callers today pass a
# literal, so interpolating one would be harmless — but a helper that accepts SQL as
# a string is only safe until someone forwards a request parameter into it.
_ORDERINGS = {"id": "ORDER BY id", "random": "ORDER BY random()"}

# Everything a persona query binds: scalars for equality and range, trait scores for
# the level bounds, and lists for the ANY(...) filters.
type SqlParam = str | int | float | list[str] | list[int] | np.ndarray


def _fetch_personas(
    conn: psycopg.Connection, sql: str, params: Sequence[SqlParam]
) -> list[Persona]:
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(sql, params).fetchall()
    return [_persona_from_row(cast(PersonaRow, row)) for row in rows]


async def _afetch_personas(
    conn: psycopg.AsyncConnection, sql: str, params: Sequence[SqlParam]
) -> list[Persona]:
    """The request path's twin of `_fetch_personas`.

    Three lines of cursor plumbing duplicated rather than one implementation
    shared, because the alternative is worse: `_fetch_personas` also serves the
    seed and the pool audit, which are scripts with no event loop, and making
    them async to spare this would drag `asyncio.run` into two command-line
    tools to save four lines. The row mapping — the part with judgment in it —
    is `_persona_from_row`, and both call it.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return [_persona_from_row(cast(PersonaRow, row)) for row in rows]


def _read_personas(
    conn: psycopg.Connection,
    *,
    order: Literal["id", "random"],
    limit: int | None = None,
) -> list[Persona]:
    clause = _ORDERINGS[order] + (" LIMIT %s" if limit is not None else "")
    return _fetch_personas(
        conn,
        f"SELECT {_PERSONA_COLUMNS} FROM personas {clause}",
        [] if limit is None else [limit],
    )


def load_pool(conn: psycopg.Connection) -> list[Persona]:
    """Every persona, in id order — the aggregate view pool QC audits."""
    return _read_personas(conn, order="id")


def load_persona_sample(conn: psycopg.Connection, *, limit: int) -> list[Persona]:
    """A random sample, for the plausibility judge — which pays per persona, so it
    reads a sample rather than the pool."""
    return _read_personas(conn, order="random", limit=limit)


async def retrieve_panel(
    conn: psycopg.AsyncConnection,
    query: TargetQuery,
    *,
    size: int,
    seed: int,
) -> list[Persona]:
    """Retrieve a panel: every requested attribute filters, then a uniform sample.

    Filtering rather than ranking is what makes the panel an audience instead of a
    tail. The pool is distributionally grounded by construction — demographics
    from the OECD joint tables, Big Five from age- and gender-conditioned norms — so a
    uniform draw inside the filter already carries a realistic spread, where taking
    the top `size` by any score returns the extremes of it.

    The sample is keyed on `seed`: hashing it with the persona id gives an ordering
    that is reproducible per seed, independent of insertion order, and needs no
    server-side random state a second query could disturb. Two seeds are two
    independent draws of the same target, which is what makes sample stability
    measurable.

    Returns fewer than `size` when the target matches fewer — a shortfall is the
    caller's to report, and raising here would turn a thin panel into no panel.
    """
    if size < 1:
        raise ValueError(f"a panel needs at least one persona, got {size}")

    # Every fragment below is a literal; only values reach the database as
    # parameters, and `%s` placeholders stay positional with `params`.
    conditions = ["country = ANY(%s)", "age BETWEEN %s AND %s"]
    params: list[SqlParam] = [
        [country.value for country in query.countries],
        query.min_age,
        query.max_age,
    ]
    if query.gender is not None:
        conditions.append("gender = %s")
        params.append(query.gender)
    if query.income_quintiles:
        conditions.append("income_quintile = ANY(%s)")
        params.append(list(query.income_quintiles))
    if query.education:
        conditions.append("education = ANY(%s)")
        params.append([level.value for level in query.education])
    for requested in query.traits:
        # The column name is the trait name, both taken from `TraitName`; the
        # comparison comes from `LEVEL_BOUNDS`. Neither is caller-supplied text, and
        # the score itself is bound as a parameter.
        for comparison, bound in LEVEL_BOUNDS[requested.level]:
            conditions.append(f"{requested.trait} {comparison} %s")
            params.append(bound)

    params += [str(seed), size]

    # Ties break on id, so the panel cannot vary run to run for a reason the customer
    # could not see. Only an md5 collision could reach it, but the ordering has to be
    # total for `LIMIT` to mean anything.
    return await _afetch_personas(
        conn,
        f"SELECT {_PERSONA_COLUMNS} FROM personas "
        f"WHERE {' AND '.join(conditions)} "
        "ORDER BY md5(id || %s::text), id LIMIT %s",
        params,
    )


async def nearest_panelists(
    conn: psycopg.AsyncConnection,
    *,
    embedding: Sequence[float],
    panel_ids: Sequence[str],
    limit: int,
) -> list[Persona]:
    """The panelists whose summaries are nearest to `embedding`, nearest first.

    Panel-only by contract: `panel_ids` are the voters of the current test, and
    nobody outside them may appear — the analyst talks about the people in the
    report, not the whole pool. An empty `panel_ids` returns
    nobody, never everybody.
    """
    # `<=>` is cosine distance; the index opclass in schema.sql must agree
    # (vector_cosine_ops), or the planner quietly ignores the index.
    return await _afetch_personas(
        conn,
        f"SELECT {_PERSONA_COLUMNS} FROM personas "
        "WHERE id = ANY(%s) "
        "ORDER BY summary_embedding <=> %s "
        "LIMIT %s",
        [list(panel_ids), np.array(embedding), limit],
    )


class VoteRow(TypedDict):
    """One `votes` row as `load_votes` selects it — same contract as `PersonaRow`:
    the SELECT list and the field reads share one spelling."""

    request_fingerprint: str
    persona_id: str
    test_id: str
    chosen_variant_id: str
    presentation_order: list[str]
    reason: str


_VOTE_COLUMNS = ", ".join(VoteRow.__annotations__)


async def store_votes(
    conn: psycopg.AsyncConnection, votes: Mapping[str, VoteRecord]
) -> int:
    """Append newly cast votes to the ledger; return how many were new.

    `ON CONFLICT DO NOTHING`, never update: votes are paid model output, and the
    first vote stored under a fingerprint is *the* vote for that question, by the
    ledger's append-only rule. A colliding write is a concurrent run that paid twice for
    the same answer — regrettable, but not a reason to rewrite history.
    """
    written = 0
    async with conn.transaction():
        for fingerprint, record in votes.items():
            # Columns spelled literally, not joined from `VoteRow`: the values
            # below are hand-ordered, and every column is text, so a reordered
            # TypedDict would land them in the wrong columns without an error.
            result = await conn.execute(
                """
                INSERT INTO votes (request_fingerprint, persona_id, test_id,
                    chosen_variant_id, presentation_order, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_fingerprint) DO NOTHING
                """,
                (
                    fingerprint,
                    record.persona_id,
                    record.test_id,
                    record.chosen_variant_id,
                    record.presentation_order,
                    record.reason,
                ),
            )
            written += result.rowcount
    return written


async def load_votes(
    conn: psycopg.AsyncConnection, fingerprints: Sequence[str]
) -> dict[str, VoteRecord]:
    """The cached votes among `fingerprints`, keyed back on the fingerprint.

    `test_id` comes back as stored — the run that paid for the vote, not the run
    reading it — so a resumed run's records carry their true provenance.
    """
    if not fingerprints:
        return {}
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {_VOTE_COLUMNS} FROM votes WHERE request_fingerprint = ANY(%s)",
            [list(fingerprints)],
        )
        rows = await cur.fetchall()
    return {
        row["request_fingerprint"]: VoteRecord(
            persona_id=row["persona_id"],
            test_id=row["test_id"],
            chosen_variant_id=row["chosen_variant_id"],
            presentation_order=row["presentation_order"],
            reason=row["reason"],
        )
        for row in (cast(VoteRow, r) for r in rows)
    }
