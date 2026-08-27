"""Persist assembled personas to Postgres + pgvector.

The connection is injected (not built from settings) so this is testable against
a throwaway container without live credentials. Idempotent: re-running the seed
skips personas already present.
"""

from collections.abc import Iterable, Mapping, Sequence
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

# Columns added after the first schema shipped. `CREATE TABLE IF NOT EXISTS` will
# not add them to an existing table, so `apply_schema` probes for them; extend this
# whenever a column is added rather than writing a second probe.
_REQUIRED_COLUMNS = ("summary_embedding",)


def apply_schema(conn: psycopg.Connection) -> None:
    """Create the pool schema if absent (idempotent), then refuse a stale one.

    `CREATE … IF NOT EXISTS` silently accepts an out-of-date table, and the
    resulting failure is invisible rather than loud: a pool seeded before the
    embedding column existed makes every id a resume-skip, so no insert ever
    names the missing column and the run reports "0 written, 200 already
    present" over a pool with no embeddings.
    """
    try:
        # The index statement references summary_embedding, so on a stale table
        # schema.sql itself now fails before the probe — same cause, same
        # remedy, so both paths land in the one curated error below.
        conn.execute(_SCHEMA_SQL)
        conn.commit()
        conn.execute(f"SELECT {', '.join(_REQUIRED_COLUMNS)} FROM personas LIMIT 0")
    except psycopg.errors.UndefinedColumn as error:
        conn.rollback()
        raise RuntimeError(
            "the personas table is missing a column this build writes "
            f"({', '.join(_REQUIRED_COLUMNS)}). Drop the personas table and reseed: "
            "its columns are a pure function of the master seed, so no information "
            "is lost. Do not drop the whole database — the votes ledger is paid "
            "model output and cannot be regenerated."
        ) from error


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
    conn.execute(
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
    conn.commit()


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
