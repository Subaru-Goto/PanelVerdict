"""Vote-cost calibration (010a): what does one panel vote actually cost?

The project has no per-test cost estimate — the old one was retracted, not corrected —
so three sibling tickets are planning against a blank. This spends a fraction of a cent
to replace it with a measurement.

It drives `collect_panel_votes`, not a private thread pool, so what gets measured is the
path that ships. Reading it any other way would produce a number for a harness.

Two arms by default. `default` sends no reasoning parameter at all, which is the
configuration every existing measurement was taken under; `low` is the only lever that
reaches the dominant cost term, since reasoning tokens bill at the output rate and a
prompt cache cannot fire at our prompt size. The comparison is the point — nothing here
adopts an effort, because doing so would retire 014's first-position rate and 015's
framing sensitivity until their harness is re-run.

    python -m experiments.vote_cost --dry-run
    python -m experiments.vote_cost --out out/cost.jsonl
    python -m experiments.vote_cost --report out/cost.jsonl

Ten votes is not a distribution. It settles an order of magnitude, and 010c's first real
200-vote run supersedes it.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, quantiles

from app.config import settings
from app.llm import OpenRouterPanelLLM, ReasoningEffort
from app.panel import FIXED_PANEL
from app.vote import ORDER_SEED, VoteUsage, collect_panel_votes, total_usage

# panel-model-selection.md:19, verified against OpenRouter's model page 2026-07-17. Held
# here so the derived figure can be checked against the `cost` the provider reports: the
# two disagreeing is a finding, and it cannot be one if only the provider's number is
# recorded.
USD_PER_INPUT_TOKEN = 0.25 / 1_000_000
USD_PER_OUTPUT_TOKEN = 2.0 / 1_000_000

# Arbitrary, and only their length matters: prompt tokens are what a cost reading is
# sensitive to, so these are ordinary marketing-headline length rather than "A"/"B".
HEADLINES = {
    "a": "Free delivery on every order",
    "b": "A $14.99 handling fee applies to every order",
}

DEFAULT_ARMS: tuple[ReasoningEffort | None, ...] = (None, "low")

# FIXED_PANEL is five personas, so two replicates is the ticket's ten votes per arm. The
# seed moves with the replicate, which varies who sees which order rather than repeating
# one assignment twice.
DEFAULT_REPLICATES = 2


@dataclass(frozen=True)
class CostRow:
    arm: str
    replicate: int
    persona_id: str
    input_tokens: int | None
    cached_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    cost: float | None
    seconds: float | None


def _arm_name(effort: ReasoningEffort | None) -> str:
    return effort or "default"


def _rows(
    arm: ReasoningEffort | None, replicate: int, panel_ids: list[str], usage: tuple
) -> list[CostRow]:
    return [
        CostRow(
            arm=_arm_name(arm),
            replicate=replicate,
            persona_id=persona_id,
            input_tokens=u.input_tokens if u else None,
            cached_tokens=u.cached_tokens if u else None,
            output_tokens=u.output_tokens if u else None,
            reasoning_tokens=u.reasoning_tokens if u else None,
            cost=u.cost if u else None,
            seconds=u.seconds if u else None,
        )
        for persona_id, u in zip(panel_ids, usage)
    ]


def collect_cost_rows(
    *, arms: tuple[ReasoningEffort | None, ...], replicates: int, api_key: str
) -> list[CostRow]:
    """Vote the panel once per arm per replicate, keeping every vote's usage."""
    rows: list[CostRow] = []
    for arm in arms:
        llm = OpenRouterPanelLLM(
            api_key=api_key,
            base_url=settings.openrouter_base_url,
            model=settings.panel_model,
            reasoning_effort=arm,
        )
        for replicate in range(replicates):
            votes = collect_panel_votes(
                test_id=f"cost-{_arm_name(arm)}-{replicate}",
                variants=HEADLINES,
                panel=FIXED_PANEL,
                llm=llm,
                seed=ORDER_SEED + replicate,
            )
            for failure in votes.failures:
                print(
                    f"  ! {_arm_name(arm)}/{replicate} {failure.persona_id}: "
                    f"{failure.error}"
                )
            rows += _rows(
                arm,
                replicate,
                [record.persona_id for record in votes.records],
                votes.usage,
            )
    return rows


def _spread(values: list[float]) -> str:
    """min/mean/max, plus p95 once there are enough values for it to mean anything."""
    if not values:
        return "unreported"
    body = f"min {min(values):.4g}  mean {mean(values):.4g}  max {max(values):.4g}"
    if len(values) >= 4:
        body += f"  p95 {quantiles(values, n=20)[18]:.4g}"
    return body


def report(rows: list[CostRow]) -> None:
    """Print each arm's reading, and the two comparisons the ticket exists to make."""
    for arm in dict.fromkeys(row.arm for row in rows):
        arm_rows = [row for row in rows if row.arm == arm]
        usage = tuple(
            VoteUsage(
                input_tokens=row.input_tokens or 0,
                cached_tokens=row.cached_tokens,
                output_tokens=row.output_tokens or 0,
                reasoning_tokens=row.reasoning_tokens,
                cost=row.cost,
                seconds=row.seconds or 0.0,
            )
            if row.input_tokens is not None
            else None
            for row in arm_rows
        )
        totals = total_usage(usage)
        reported = [u for u in usage if u is not None]

        print(
            f"\n=== arm: {arm} ({totals.votes} votes, "
            f"{totals.usage_reported} with usage) ==="
        )
        print(
            f"  prompt tokens    {_spread([float(u.input_tokens) for u in reported])}"
        )
        print(
            f"  output tokens    {_spread([float(u.output_tokens) for u in reported])}"
        )
        print(
            f"  reasoning tokens {_spread([float(u.reasoning_tokens) for u in reported if u.reasoning_tokens is not None])}"
            f"  ({totals.reasoning_reported}/{totals.votes} reported)"
        )
        print(f"  latency seconds  {_spread([u.seconds for u in reported])}")
        print(
            f"  cached tokens    {totals.cached_tokens} over "
            f"{totals.cached_reported}/{totals.votes} votes reporting"
        )

        # Reasoning tokens are a *subset* of the output tokens, not a third term — the
        # provider reports them as a breakdown of `completion_tokens`. Adding them again
        # would roughly double the output side of every estimate.
        derived = (
            totals.input_tokens * USD_PER_INPUT_TOKEN
            + totals.output_tokens * USD_PER_OUTPUT_TOKEN
        )
        per_vote_reported = (
            totals.cost / totals.cost_reported if totals.cost_reported else None
        )
        print(
            f"  cost reported    ${totals.cost:.6f} over "
            f"{totals.cost_reported}/{totals.votes} votes"
        )
        print(f"  cost derived     ${derived:.6f} at $0.25/$2 per M")
        if per_vote_reported is not None:
            print(
                f"  → per 200 votes  ${per_vote_reported * 200:.4f} reported, "
                f"${derived / max(totals.usage_reported, 1) * 200:.4f} derived"
            )

    # Reasoning must visibly differ between arms, or a wired-up effort and an ignored one
    # look identical and "low does not help" is indistinguishable from "low never
    # applied".
    by_arm = {
        arm: [
            row.reasoning_tokens
            for row in rows
            if row.arm == arm and row.reasoning_tokens is not None
        ]
        for arm in dict.fromkeys(row.arm for row in rows)
    }
    if len([a for a, v in by_arm.items() if v]) > 1:
        means = {arm: mean(v) for arm, v in by_arm.items() if v}
        print(
            f"\nreasoning tokens by arm: { {a: round(m, 1) for a, m in means.items()} }"
        )
        if len(set(round(m) for m in means.values())) == 1:
            print("  !! arms did not differ — suspect the parameter before the finding")


def _write(rows: list[CostRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(row)) + "\n" for row in rows))


def _read(path: Path) -> list[CostRow]:
    return [
        CostRow(**json.loads(line)) for line in path.read_text().splitlines() if line
    ]


def _effort(value: str) -> ReasoningEffort | None:
    if value == "default":
        return None
    allowed = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
    if value not in allowed:
        raise argparse.ArgumentTypeError(
            f"unknown effort {value!r}; expected default or one of {', '.join(allowed)}"
        )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arms",
        type=lambda v: tuple(_effort(a.strip()) for a in v.split(",")),
        default=DEFAULT_ARMS,
    )
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--out", type=Path, default=Path("out/cost.jsonl"))
    parser.add_argument(
        "--report", type=Path, help="read a previous run and re-print it"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan and spend nothing"
    )
    args = parser.parse_args()

    if args.report:
        report(_read(args.report))
        return

    votes = len(args.arms) * args.replicates * len(FIXED_PANEL)
    print(
        f"{len(args.arms)} arm(s) {[_arm_name(a) for a in args.arms]} × "
        f"{args.replicates} replicate(s) × {len(FIXED_PANEL)} personas = {votes} paid votes"
    )
    if args.dry_run:
        return
    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot run the panel.")

    rows = collect_cost_rows(
        arms=args.arms,
        replicates=args.replicates,
        api_key=settings.openrouter_api_key.get_secret_value(),
    )
    _write(rows, args.out)
    print(f"wrote {len(rows)} rows to {args.out}")
    report(rows)


if __name__ == "__main__":
    main()
