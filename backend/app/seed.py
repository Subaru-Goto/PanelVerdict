"""Seed the persona pool: assemble each persona, then persist it, idempotently.

Run: python -m app.seed --size dev|full --seed N [--countries US,JP,DE]

Resumable — already-persisted personas are skipped before assembly, so a re-run
never re-pays the LLM/embedding cost for what it already has.
"""

import argparse
import logging
from dataclasses import dataclass

import psycopg

from app.assembly import assemble_pool
from app.config import settings
from app.interests import Embedder, InterestLLM
from app.llm import OpenRouterEmbedder, OpenRouterInterestLLM, OpenRouterJudge
from app.persistence import persist_persona, prepare_connection
from app.qc import format_qc_report, run_qc
from app.schemas import Locale

_POOL_SIZES = {"dev": 200, "full": 5000}


@dataclass(frozen=True)
class SeedResult:
    """`skipped` = already in the pool (healthy resume); `failed` = interest
    generation gave up after retries (pool is short — a re-run retries these)."""

    requested: int
    written: int
    skipped: int
    failed: int


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
    llm: InterestLLM,
    embedder: Embedder,
) -> SeedResult:
    """Assemble and persist the pool, skipping personas already present.

    Existing ids are read once and handed to `assemble_pool` as a skip set, so a
    resumed run never assembles (or calls the LLM for) what it already has.
    """
    requested = sum(quotas.values())
    failed: list[str] = []
    written = sum(
        persist_persona(conn, assembled)
        for assembled in assemble_pool(
            quotas,
            master_seed=master_seed,
            llm=llm,
            embedder=embedder,
            skip=_existing_ids(conn),
            on_failure=failed.append,
        )
    )
    return SeedResult(
        requested=requested,
        written=written,
        skipped=requested - written - len(failed),
        failed=len(failed),
    )


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the persona pool.")
    add_pool_args(parser)
    parser.add_argument("--qc-sample", type=int, default=50)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot generate the pool.")
    api_key = settings.openrouter_api_key.get_secret_value()
    llm = OpenRouterInterestLLM(
        api_key=api_key,
        base_url=settings.openrouter_base_url,
        model=settings.interest_model,
    )
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

    quotas = build_quotas(args.size, args.countries)
    requested = sum(quotas.values())
    # autocommit, or the per-persona transaction blocks silently become
    # savepoints inside one run-long implicit transaction — an interrupt would
    # then roll back every persona (and its paid LLM work) instead of just the
    # one in flight
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        prepare_connection(conn)
        already = len(_existing_ids(conn))
        print(
            f"Seeding '{args.size}' pool (seed={args.seed}): ~{max(0, requested - already)} "
            f"personas to generate, {already} already in the pool."
        )
        result = seed_pool(
            conn, quotas, master_seed=args.seed, llm=llm, embedder=embedder
        )
        print(
            f"Done: {result.written} written, {result.skipped} already present, "
            f"{result.failed} failed (re-run to retry)."
        )
        report = run_qc(conn, judge=judge, sample_size=args.qc_sample)
    print(format_qc_report(report))


if __name__ == "__main__":
    main()
