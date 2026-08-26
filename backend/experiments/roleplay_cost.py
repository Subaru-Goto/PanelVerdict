"""Rewrite-and-check cost calibration: what does one role-play call actually cost?

094 decided the checks get a per-caller daily bound whose figure comes from a
measurement, per the no-unsourced-constants rule. `USD_PER_ROLEPLAY` is the
translator's upper bound — honest, but measured on a different job, so it sizes a
ceiling rather than a bound. This reads the two calls that actually ship: the **rewrite**
(audience words → one panelist instruction) and the **check** (an edited or
client-supplied instruction → a verdict), each against the same eight ordinary
audiences the guard run scored as the feature's legitimate traffic.

The client is built with the generator's own parameters but `include_raw=True`,
because the shipped binding discards the AIMessage and with it the only place the
provider's bill survives. The parameters are restated rather than shared — if
`OpenRouterRolePlayGenerator.__init__` changes, this measures the old call until
it is updated to match.

    python -m experiments.roleplay_cost --dry-run
    python -m experiments.roleplay_cost --out experiments/out/roleplay-cost.jsonl
    python -m experiments.roleplay_cost --report experiments/out/roleplay-cost.jsonl

Eight probes x a few replicates settles an order of magnitude. It is not a
distribution, and nothing here should be read as one.
"""

import argparse
import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from time import perf_counter

from app.config import LANGCHAIN_INTEGRATION, USD_PER_ROLEPLAY, settings
from app.llm import (
    TARGET_MAX_COMPLETION_TOKENS,
    TARGET_REASONING_EFFORT,
    VOTE_READ_TIMEOUT_SECONDS,
    _vote_usage,
)
from app.roleplay import (
    RolePlayOutcome,
    RolePlayVerdict,
    build_check_messages,
    build_roleplay_messages,
)
from app.vote import VoteUsage
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, BaseMessage

from experiments.roleplay_guard import LEGITIMATE

DEFAULT_REPLICATES = 3


@dataclass(frozen=True)
class CostRow:
    """One call's usage, labelled with what kind of call and which probe.

    `usage` is held whole for vote_cost's reason: flattening `VoteUsage` into
    columns is where its optional fields would quietly acquire zeros. `error` is
    set exactly when the call produced nothing to measure a successor with — a
    refused or unparseable rewrite still has usage of its own, but leaves no
    instruction for the check arm.
    """

    kind: str  # "rewrite" | "check"
    probe: str
    replicate: int
    usage: VoteUsage | None
    error: str | None = None


def _timed(model, messages: list[BaseMessage]) -> tuple[dict, VoteUsage | None]:
    """Invoke an `include_raw` binding and read the bill off the raw message.

    `_vote_usage` is llm.py's own reader, imported rather than retyped: it is the
    one confirmed on the wire to find the provider's `cost`, and a copy here
    would drift from it silently.
    """
    started = perf_counter()
    result = model.invoke(messages)
    seconds = perf_counter() - started
    raw = result.get("raw")
    usage = _vote_usage(raw, seconds) if isinstance(raw, AIMessage) else None
    return result, usage


def collect_cost_rows(*, replicates: int, api_key: str) -> list[CostRow]:
    """Rewrite each probe, then check the instruction that rewrite produced.

    Chained rather than checking canned sentences, because that is the shipped
    sequence: every checked sentence starts life as a draft. The check's cost is
    prompt-length-sensitive and drafts are the realistic prompt.
    """
    nonce = f"<<{secrets.token_hex(8)}>>"
    client = init_chat_model(
        model=settings.targeting_model,
        model_provider=LANGCHAIN_INTEGRATION,
        base_url=settings.openrouter_base_url,
        api_key=api_key,
        max_retries=2,
        timeout=VOTE_READ_TIMEOUT_SECONDS,
        max_tokens=TARGET_MAX_COMPLETION_TOKENS,
        reasoning_effort=TARGET_REASONING_EFFORT,
    )
    drafter = client.with_structured_output(RolePlayOutcome, include_raw=True)
    checker = client.with_structured_output(RolePlayVerdict, include_raw=True)

    rows: list[CostRow] = []
    for replicate in range(replicates):
        for probe in LEGITIMATE:
            result, usage = _timed(
                drafter, build_roleplay_messages(probe.words, nonce=nonce)
            )
            drafted = result.get("parsed")
            instruction = (
                drafted.instruction
                if isinstance(drafted, RolePlayOutcome) and drafted.refusal is None
                else ""
            )
            rows.append(
                CostRow(
                    kind="rewrite",
                    probe=probe.id,
                    replicate=replicate,
                    usage=usage,
                    error=None if instruction else "no instruction to hand on",
                )
            )
            if not instruction:
                continue
            _, check_usage = _timed(
                checker, build_check_messages(instruction, nonce=nonce)
            )
            rows.append(
                CostRow(
                    kind="check",
                    probe=probe.id,
                    replicate=replicate,
                    usage=check_usage,
                )
            )
    return rows


def _spread(values: list[float]) -> str:
    if not values:
        return "unreported"
    return f"min {min(values):.4g}  mean {mean(values):.4g}  max {max(values):.4g}"


def report(rows: list[CostRow]) -> None:
    """Each kind's reading, set against the ceiling every charge uses today."""
    for kind in ("rewrite", "check"):
        kind_rows = [row for row in rows if row.kind == kind]
        reported = [row.usage for row in kind_rows if row.usage is not None]
        costs = [u.cost for u in reported if u.cost is not None]

        print(f"\n=== {kind} ({len(kind_rows)} calls, {len(reported)} with usage) ===")
        print(
            f"  prompt tokens    {_spread([float(u.input_tokens) for u in reported])}"
        )
        print(
            f"  output tokens    {_spread([float(u.output_tokens) for u in reported])}"
        )
        print(
            "  reasoning tokens "
            + _spread(
                [
                    float(u.reasoning_tokens)
                    for u in reported
                    if u.reasoning_tokens is not None
                ]
            )
        )
        print(f"  latency seconds  {_spread([u.seconds for u in reported])}")
        print(f"  cost reported    {_spread(costs)}  ({len(costs)}/{len(kind_rows)})")
        if costs:
            # The ceiling is what the pool is charged today; the ratio says how
            # much headroom a bound sized from it would silently include.
            print(
                f"  vs USD_PER_ROLEPLAY ${USD_PER_ROLEPLAY}: "
                f"max is {max(costs) / USD_PER_ROLEPLAY:.0%} of the ceiling"
            )
        failed = [row for row in kind_rows if row.error is not None]
        if failed:
            print(f"  !! {len(failed)} call(s) produced nothing to hand on")


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument(
        "--out", type=Path, default=Path("experiments/out/roleplay-cost.jsonl")
    )
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

    calls = len(LEGITIMATE) * args.replicates * 2
    print(
        f"{len(LEGITIMATE)} probes × {args.replicates} replicate(s) × 2 kinds "
        f"= up to {calls} paid calls (~${calls * USD_PER_ROLEPLAY:.3f} at the ceiling)"
    )
    if args.dry_run:
        return
    if settings.openrouter_api_key is None:
        raise SystemExit("openrouter_api_key is not set; cannot run the generator.")

    rows = collect_cost_rows(
        replicates=args.replicates,
        api_key=settings.openrouter_api_key.get_secret_value(),
    )
    _write(rows, args.out)
    print(f"wrote {len(rows)} rows to {args.out}")
    report(rows)


if __name__ == "__main__":
    main()
