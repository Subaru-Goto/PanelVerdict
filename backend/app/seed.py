"""Seed the persona pool: assemble each persona, then persist it, idempotently.

Run: python -m app.seed --size dev|full --seed N [--countries US,JP,DE]

Resumable — already-persisted personas are skipped before assembly, so a re-run
never re-pays the LLM/embedding cost for what it already has.
"""

import argparse
import logging
from dataclasses import dataclass

import psycopg

from app.assembly import Embedder, assemble_pool
from app.config import settings
from app.llm import OpenRouterEmbedder, OpenRouterJudge
from app.corpus import DOCUMENTS, seed_corpus
from app.persistence import persist_persona, prepare_connection
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
        return conn.execute("SELECT count(*) FROM personas").fetchone()[0]
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
        "--dry-run",
        action="store_true",
        help="report what a run would generate and exit; needs no API key, "
        "writes nothing, and calls nothing paid",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

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
