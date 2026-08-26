"""Vote-cost calibration: what does one panel vote actually cost?

Drives `collect_panel_votes` rather than a private thread pool, so the reading describes
the path that ships. A private pool would be simpler and would measure this harness.

Two arms. `default` sends no reasoning parameter at all, which is the configuration every
existing measurement in this project was taken under; `low` is the only lever that reaches
the dominant cost term, since reasoning tokens bill at the output rate and a prompt cache
cannot fire at our prompt size. It produces the comparison and adopts neither, because
changing the effort changes what the panel is: the measured first-position rate and the
question-wording sensitivity were both taken at the default, and neither survives the
switch without being measured again.

    python -m experiments.vote_cost --dry-run
    python -m experiments.vote_cost --out experiments/out/cost.jsonl
    python -m experiments.vote_cost --report experiments/out/cost.jsonl

Ten votes per arm settles an order of magnitude. It is not a distribution, and nothing
here should be read as one.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, quantiles
from typing import get_args

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

# The default panel size, chosen so that a practical tie is expressible at the ±7 ROPE.
# A per-vote figure is extrapolated to it because the question behind this harness is what
# one full test costs.
PANEL_SIZE = 200

DEFAULT_ARMS: tuple[ReasoningEffort | None, ...] = (None, "low")

# FIXED_PANEL is five personas, so two replicates is the ticket's ten votes per arm. The
# seed moves with the replicate, which varies who sees which order rather than repeating
# one assignment twice.
DEFAULT_REPLICATES = 2


@dataclass(frozen=True)
class CostRow:
    """One vote's usage, labelled with the arm and panelist it came from.

    `usage` is held whole rather than flattened into columns: a copy of every `VoteUsage`
    field would have to be mapped out and back, and each hop is somewhere the optional
    fields could quietly acquire a zero.

    `error` is set exactly when the vote failed, which is also when `usage` is None — a
    refused vote produces a row so that a re-read can see the refusal, since `records`
    cannot carry one.
    """

    arm: str
    replicate: int
    persona_id: str
    usage: VoteUsage | None
    error: str | None = None


def _arm_name(effort: ReasoningEffort | None) -> str:
    return effort or "default"


def _rows(
    arm: ReasoningEffort | None,
    replicate: int,
    panel_ids: list[str],
    usage: tuple[VoteUsage | None, ...],
) -> list[CostRow]:
    return [
        CostRow(arm=_arm_name(arm), replicate=replicate, persona_id=persona_id, usage=u)
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
            model=settings.panel.model,
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
            rows += _rows(
                arm,
                replicate,
                [record.persona_id for record in votes.records],
                votes.usage,
            )
            # A refused vote is the schema-compliance signal: cheaper reasoning that stops
            # satisfying the response schema turns a saving into a lost vote, which is
            # strictly worse than not saving. Recorded as a row, with the exception type
            # only — the full message carries the model's own output.
            rows += [
                CostRow(
                    arm=_arm_name(arm),
                    replicate=replicate,
                    persona_id=failure.persona_id,
                    usage=None,
                    error=failure.error.split(":")[0],
                )
                for failure in votes.failures
            ]
    return rows


# `quantiles(n=20)` needs at least 20 points to place every cut between two observations;
# below that it interpolates, and below four it is reporting the maximum under another
# name. So the p95 is suppressed rather than printed from a handful of values.
#
# p95 and not the p99 a read timeout wants: a p99 needs on the order of a hundred
# observations before it stops being the single slowest one. Ten votes cannot supply it,
# and the first full-panel run can.
_MIN_FOR_PERCENTILE = 4


def _spread(values: list[float]) -> str:
    """min/mean/max, plus a p95 once there are enough values to place one."""
    if not values:
        return "unreported"
    body = f"min {min(values):.4g}  mean {mean(values):.4g}  max {max(values):.4g}"
    if len(values) >= _MIN_FOR_PERCENTILE:
        body += f"  p95 {quantiles(values, n=20)[18]:.4g}"
    return body


def report(rows: list[CostRow]) -> None:
    """Print each arm's reading, and set the two figures against each other."""
    for arm in dict.fromkeys(row.arm for row in rows):
        arm_rows = [row for row in rows if row.arm == arm]
        usage = tuple(row.usage for row in arm_rows)
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
        refused = [row for row in arm_rows if row.error is not None]
        if refused:
            print(
                f"  !! {len(refused)} vote(s) never returned a parseable answer: "
                f"{', '.join(sorted({row.error or '' for row in refused}))}"
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
            per_vote_derived = derived / max(totals.usage_reported, 1)
            print(
                f"  → per {PANEL_SIZE} votes  "
                f"${per_vote_reported * PANEL_SIZE:.4f} reported, "
                f"${per_vote_derived * PANEL_SIZE:.4f} derived"
            )

    # Reasoning must visibly differ between arms, or a wired-up effort and an ignored one
    # look identical and "low does not help" is indistinguishable from "low never
    # applied".
    by_arm = {
        arm: [
            row.usage.reasoning_tokens
            for row in rows
            if row.arm == arm
            and row.usage is not None
            and row.usage.reasoning_tokens is not None
        ]
        for arm in dict.fromkeys(row.arm for row in rows)
    }
    if len([a for a, v in by_arm.items() if v]) > 1:
        means = {arm: mean(v) for arm, v in by_arm.items() if v}
        print(
            f"\nreasoning tokens by arm: { {a: round(m, 1) for a, m in means.items()} }"
        )
        if len(set(means.values())) == 1:
            print("  !! arms did not differ — suspect the parameter before the finding")


def _write(rows: list[CostRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(row)) + "\n" for row in rows))


def _read(path: Path) -> list[CostRow]:
    rows = []
    for line in path.read_text().splitlines():
        if not line:
            continue
        row = json.loads(line)
        usage = row.pop("usage")
        rows.append(CostRow(**row, usage=VoteUsage(**usage) if usage else None))
    return rows


# Read off the type rather than re-listed, so a level added there reaches the CLI. A
# second copy would silently reject the new level, and an effort the provider does not
# recognise is accepted by the request and then does nothing.
EFFORTS: dict[str, ReasoningEffort | None] = {"default": None} | {
    effort: effort for effort in get_args(ReasoningEffort.__value__)
}


def _effort(value: str) -> ReasoningEffort | None:
    if value not in EFFORTS:
        raise argparse.ArgumentTypeError(
            f"unknown effort {value!r}; expected one of {', '.join(EFFORTS)}"
        )
    return EFFORTS[value]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--arms",
        type=lambda v: tuple(_effort(a.strip()) for a in v.split(",")),
        default=DEFAULT_ARMS,
    )
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--out", type=Path, default=Path("experiments/out/cost.jsonl"))
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
