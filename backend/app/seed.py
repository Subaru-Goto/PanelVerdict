"""Seed the persona pool: assemble each persona, then persist it, idempotently.

Run: python -m app.seed --size dev|full --seed N [--countries US,JP,DE]

Resumable — already-persisted personas are skipped before assembly, so a re-run
never re-pays the LLM/embedding cost for what it already has.
"""

import argparse
from dataclasses import dataclass

import psycopg

from app.assembly import Embedder, assemble_pool
from app.config import settings
from app.db import CONNECT_TIMEOUT_SECONDS
from app.llm import OpenRouterEmbedder, OpenRouterJudge
from app.logs import configure_logging
from app.corpus import DOCUMENTS, seed_corpus
from app.persistence import (
    missing_columns,
    persist_persona,
    prepare_connection,
    schema_columns,
)
from app.plausibility import format_report, run_plausibility_qc
from app.schemas import Locale

_POOL_SIZES = {"dev": 200, "full": 5000}


@dataclass(frozen=True)
class SeedResult:
    """`skipped` = already in the pool, i.e. a healthy resume."""

    requested: int
    written: int
    skipped: int


def build_quotas(size: str, countries: list[Locale]) -> dict[Locale, int]:
    """Split a pool size across countries — the cross-country quota knob. The
    remainder is spread over the first countries so the totals hit the target
    exactly (5000, not 4998)."""
    base, extra = divmod(_POOL_SIZES[size], len(countries))
    return {
        country: base + (1 if i < extra else 0) for i, country in enumerate(countries)
    }


def _existing_ids(conn: psycopg.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT id FROM personas")}


def seed_pool(
    conn: psycopg.Connection,
    quotas: dict[Locale, int],
    *,
    master_seed: int,
    embedder: Embedder,
) -> SeedResult:
    """Assemble and persist the pool, skipping personas already present.

    Existing ids are read once and handed to `assemble_pool` as a skip set, so a
    resumed run never assembles (or embeds) what it already has.
    """
    requested = sum(quotas.values())
    written = sum(
        persist_persona(conn, assembled)
        for assembled in assemble_pool(
            quotas,
            master_seed=master_seed,
            embedder=embedder,
            skip=_existing_ids(conn),
        )
    )
    return SeedResult(requested=requested, written=written, skipped=requested - written)


def _parse_countries(value: str) -> list[Locale]:
    # dedup (order-preserving) so a "US,US" typo can't silently shrink the pool
    codes = (Locale(code.strip().upper()) for code in value.split(","))
    return list(dict.fromkeys(codes))


def add_pool_args(parser: argparse.ArgumentParser) -> None:
    """The pool-selection flags shared by the seed and echo-audit CLIs — the
    audit must accept exactly the flags a seed run used, or it recomputes
    prompt examples for a different pool than the one in the DB."""
    parser.add_argument("--size", choices=_POOL_SIZES, default="dev")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--countries", type=_parse_countries, default=list(Locale))


def _pool_size(conn: psycopg.Connection) -> int:
    """Personas already stored, tolerating a pool that has never been seeded.

    A dry run must not apply the schema — reporting what something would cost
    should not be able to change the database — so it cannot assume the table is
    there. Safe on the autocommit connection used here, where a failed statement
    leaves no aborted transaction behind.
    """
    try:
        row = conn.execute("SELECT count(*) FROM personas").fetchone()
        return row[0] if row else 0
    except psycopg.errors.UndefinedTable:
        return 0


def _reseed_corpus() -> None:
    """Rebuild only the explanation corpus (018/#124).

    Its own path because the two seeds have nothing in common but a connection.
    The pool is hundreds of paid generations and resumes; the corpus is a handful
    of embeddings over documents committed to git, and is always replaced whole.
    Editing a sentence in a document should not mean rerunning the pool.
    """
    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot embed the corpus.")
    embedder = OpenRouterEmbedder(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        prepare_connection(conn)
        print(f"Corpus: {seed_corpus(conn, embedder)} passages.")


def _check_schema() -> None:
    """Fail the build when the deployed database is behind what this build writes.

    Check only, never apply. Two reasons, and the second is the load-bearing
    one: a credential that can apply a migration is a credential CI can get
    wrong, and applying automatically is the thing 083/#173 deliberately
    deferred to launch. So this opens a plain connection, reads the catalogue,
    and exits — `deploy.md` records three deploys where a missing table meant a
    500 on every request that touched it, and a red build is the alternative.
    """
    # An unreachable or misspelled pooler host should fail this job in seconds
    # with a readable error, not sit on the OS TCP timeout while a CI runner burns.
    with psycopg.connect(
        settings.database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS
    ) as conn:
        stale = missing_columns(conn)
    if stale:
        raise SystemExit(
            "the deployed schema is behind this build: "
            + "; ".join(
                f"{table} is missing {', '.join(columns)}"
                for table, columns in sorted(stale.items())
            )
            + ". Apply app/schema.sql to the project (see docs/deploy.md) — by "
            "hand, which is the standing decision until launch."
        )
    print(
        f"Schema up to date: every column in {len(schema_columns())} tables is present."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the persona pool.")
    add_pool_args(parser)
    parser.add_argument("--qc-sample", type=int, default=50)
    parser.add_argument(
        "--corpus-only",
        action="store_true",
        help="reseed only the explanation corpus and exit. A handful of "
        "embeddings, so it costs almost nothing — which is the point: editing a "
        "document should not mean paying to regenerate the pool",
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="apply the schema and the row-level-security sweep, then exit. "
        "Writes DDL and nothing else: no personas, no corpus, no embeddings, "
        "no API key needed",
    )
    parser.add_argument(
        "--check-schema",
        action="store_true",
        help="report whether the connected database has every table and column "
        "this build writes, and exit non-zero if not. Reads only — never "
        "applies, so a SELECT-privileged credential suffices",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what a run would generate and exit; needs no API key, "
        "writes nothing, and calls nothing paid",
    )
    args = parser.parse_args()
    configure_logging()

    # Both schema paths come before everything else, including the corpus:
    # they are the two entry points that must not depend on a paid client, and
    # `--corpus-only` builds one (115/#248).
    if args.check_schema:
        _check_schema()
        return

    if args.schema_only:
        tables = schema_columns()
        listed = ", ".join(sorted(tables))
        # Checked here and not only at the usual place further down, for the
        # reason the `--corpus-only` comment below records: this branch returns
        # before ever reaching that one, so `--schema-only --dry-run` applied
        # every statement and took ACCESS EXCLUSIVE on every table in `public`
        # — against a flag whose help says it writes nothing.
        if args.dry_run:
            print(
                f"Dry run: nothing written. Would ensure {len(tables)} "
                f"tables ({listed})."
            )
            return
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            prepare_connection(conn)
        print(
            f"Schema applied: {len(tables)} tables ({listed}), "
            "row-level security swept."
        )
        return

    if args.corpus_only:
        # The dry-run check has to happen here, not at its usual place further
        # down: the corpus path returns before ever reaching that one, so
        # `--corpus-only --dry-run` applied schema DDL, paid for embeddings and
        # replaced the live table — against a flag whose help says it writes
        # nothing and calls nothing paid.
        print(f"Corpus: {len(DOCUMENTS)} passages to embed and replace.")
        if args.dry_run:
            print("Dry run: nothing written, nothing embedded.")
            return
        _reseed_corpus()
        return

    quotas = build_quotas(args.size, args.countries)
    requested = sum(quotas.values())
    # autocommit, or the per-persona transaction blocks silently become
    # savepoints inside one run-long implicit transaction — an interrupt would
    # then roll back every persona (and its paid LLM work) instead of just the
    # one in flight
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        # Counted before the schema is touched and before any client is built, so
        # the price of a run is knowable for free. Seeding resumes, so the spend
        # is the shortfall against the pool rather than the whole quota.
        already = _pool_size(conn)
        outstanding = max(0, requested - already)
        print(
            f"Seeding '{args.size}' pool (seed={args.seed}): ~{outstanding} "
            f"personas to generate, {already} already in the pool."
        )
        if args.dry_run:
            print(
                f"Dry run: nothing written. A full run would generate and embed "
                f"{outstanding} persona(s), then judge a sample of {args.qc_sample}."
            )
            return

        if settings.openrouter_api_key is None:
            raise SystemExit("openrouter_api_key is not set; cannot generate the pool.")
        api_key = settings.openrouter_api_key.get_secret_value()
        embedder = OpenRouterEmbedder(
            api_key=api_key,
            base_url=settings.openrouter_base_url,
            model=settings.embedding_model,
        )
        judge = OpenRouterJudge(
            api_key=api_key,
            base_url=settings.openrouter_base_url,
            model=settings.judge_model,
        )

        prepare_connection(conn)
        result = seed_pool(conn, quotas, master_seed=args.seed, embedder=embedder)
        print(f"Done: {result.written} written, {result.skipped} already present.")
        # After the pool, because both need the schema and this is the cheap
        # half: the corpus is a handful of chunks, so it is always rebuilt rather
        # than resumed. Documents live in git, so the table can only be stale.
        print(f"Corpus: {seed_corpus(conn, embedder)} passages.")
        report = run_plausibility_qc(conn, judge=judge, sample_size=args.qc_sample)
    print(format_report(report))


if __name__ == "__main__":
    main()
