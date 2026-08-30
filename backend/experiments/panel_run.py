"""One real panel run, end to end, with the receipt written down.

Drives `run_panel_test` — the same select/vote/assemble steps `/evaluate` ships,
without its panel gate — against the live adapter
and the seeded pool, so what is measured is what customers get: chunking, adaptive
stopping, the vote cache, and per-chunk commits, all under real concurrency. This is
the only module in the repo that constructs the live adapter outside FastAPI, and it
configures logging *first*, so every usage line lands (the lesson 010c's incident
taught).

Built for 010f's paired reading:

    python -m experiments.panel_run --label fixed-200 \
        --headline-a "..." --headline-b "..." --description "..." --profile prod \
        --out experiments/out/panel_run.jsonl
    python -m experiments.panel_run --report experiments/out/panel_run.jsonl

The fixed-200 arm uses two identical headlines: a true tie by construction, which the
stopping rule cannot end early (the tie stop is first reachable at the cap), so the run
buys the full-length latency distribution the read timeout needs. The savings arm uses
a pair with a clear winner and lets the stop fire for real.
"""

import argparse
import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean

import psycopg
from pgvector.psycopg import register_vector_async

from app.config import PROFILES, ProfileName, settings
from app.llm import OpenRouterPanelLLM, OpenRouterTargetTranslator
from app.pipeline import PanelTestResult, run_panel_test
from app.vote import PanelVotes, VoteUsage, total_usage


@dataclass(frozen=True)
class RunRow:
    """One panelist's outcome in one labelled run.

    `shown_first` rides beside the choice so the position-bias rate stays readable
    from the raw file alone. `usage` is None for a failure — and also for a cache
    hit, which is how a replay run's rows say "nothing was spent here".
    """

    label: str
    persona_id: str
    chosen_variant_id: str | None
    shown_first: str | None
    usage: VoteUsage | None
    error: str | None = None


@dataclass(frozen=True)
class LatencyReading:
    """Nearest-rank percentiles over the votes that reported a duration."""

    votes_timed: int
    p50: float
    p95: float
    p99: float
    slowest: float


def latency_percentiles(usage: list[VoteUsage | None]) -> LatencyReading | None:
    """Nearest-rank (the value at ceil(p·n/100), no interpolation): with 200 points
    the p99 is a real observed vote, not an average of two — the timeout will be
    compared against real durations, so it should be sourced from one. Integer
    arithmetic because 0.95 * 200 is not 190.0 in floating point."""
    seconds = sorted(u.seconds for u in usage if u is not None)
    if not seconds:
        return None

    def at(percentile: int) -> float:
        return seconds[-(-percentile * len(seconds) // 100) - 1]

    return LatencyReading(
        votes_timed=len(seconds),
        p50=at(50),
        p95=at(95),
        p99=at(99),
        slowest=seconds[-1],
    )


def rows_from_votes(label: str, votes: PanelVotes) -> list[RunRow]:
    rows = [
        RunRow(
            label=label,
            persona_id=record.persona_id,
            chosen_variant_id=record.chosen_variant_id,
            shown_first=record.presentation_order[0],
            usage=usage,
        )
        for record, usage in zip(votes.records, votes.usage)
    ]
    rows += [
        RunRow(
            label=label,
            persona_id=failure.persona_id,
            chosen_variant_id=None,
            shown_first=None,
            usage=None,
            error=failure.error,
        )
        for failure in votes.failures
    ]
    return rows


def report(rows: list[RunRow]) -> None:
    for label in dict.fromkeys(row.label for row in rows):
        ours = [row for row in rows if row.label == label]
        voted = [row for row in ours if row.error is None]
        usage = [row.usage for row in voted]
        totals = total_usage(usage)
        print(f"\n== {label}: {len(voted)} votes, {len(ours) - len(voted)} failed ==")
        print(
            f"cost ${totals.cost:.4f} over {totals.cost_reported} reporting votes"
            f" ({totals.votes - totals.usage_reported} spent nothing: cache or gap)"
        )
        reading = latency_percentiles(usage)
        if reading is None:
            print("latency: nothing timed (a full replay)")
        else:
            print(
                f"latency over {reading.votes_timed} timed votes: "
                f"p50 {reading.p50:.1f}s  p95 {reading.p95:.1f}s  "
                f"p99 {reading.p99:.1f}s  slowest {reading.slowest:.1f}s"
            )
        chosen = [row.chosen_variant_id for row in voted]
        for variant in sorted(set(chosen)):
            print(f"chose {variant}: {chosen.count(variant)}")
        first = [
            row.chosen_variant_id == row.shown_first
            for row in voted
            if row.shown_first is not None
        ]
        if first:
            print(f"picked the first-shown option: {mean(first):.2f}")


def _print_result(result: PanelTestResult) -> None:
    verdict = result.verdict
    print(f"counts: {result.counts}")
    print(f"stop_reason: {result.stop_reason}")
    print(f"tally: {result.tally.counts}")
    preferred = verdict.probability_meaningfully_preferred
    print(
        "verdict: "
        f"P(A meaningfully preferred)={preferred.a:.3f} "
        f"P(B meaningfully preferred)={preferred.b:.3f} "
        f"P(practical tie)={verdict.probability_practical_tie:.3f}"
    )
    for notice in result.notices:
        print(f"notice[{notice.severity}]: {notice.message}")


def _write(rows: list[RunRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row)) + "\n")


def _read(path: Path) -> list[RunRow]:
    rows = []
    for line in path.read_text().splitlines():
        data = json.loads(line)
        usage = data.pop("usage")
        rows.append(RunRow(**data, usage=VoteUsage(**usage) if usage else None))
    return rows


def main() -> None:
    # Before anything that could spend: the logged usage line is the receipt, and a
    # run without it is the exact failure 010c recorded.
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--label")
    parser.add_argument("--headline-a")
    parser.add_argument("--headline-b")
    parser.add_argument("--description")
    parser.add_argument("--profile", choices=list(PROFILES), default="dev")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.report:
        report(_read(args.report))
        return
    for required in ("label", "headline_a", "headline_b", "description", "out"):
        if getattr(args, required) is None:
            raise SystemExit(f"--{required.replace('_', '-')} is required to run")
    if settings.openrouter_api_key is None:
        raise SystemExit("OPENROUTER_API_KEY is not set")

    profile: ProfileName = args.profile
    llm = OpenRouterPanelLLM(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=PROFILES[profile].model,
    )
    translator = OpenRouterTargetTranslator(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.targeting_model,
    )

    # `run_panel_test` followed its callees async (111/#240). A script has no
    # event loop of its own, so it starts one here rather than the pipeline
    # keeping a sync twin for one caller.
    async def run() -> PanelTestResult:
        async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
            # The adapter, for the reason `corpus_check._with_live` records: a
            # bare connection aborts a paid run the moment anything binds a
            # numpy vector, and nothing here would catch it until it happened.
            await register_vector_async(conn)
            return await run_panel_test(
                conn,
                description=args.description,
                variants={"a": args.headline_a, "b": args.headline_b},
                size=PROFILES[profile].size,
                translator=translator,
                llm=llm,
            )

    result = asyncio.run(run())
    _write(rows_from_votes(args.label, result.votes), args.out)
    _print_result(result)


if __name__ == "__main__":
    main()
