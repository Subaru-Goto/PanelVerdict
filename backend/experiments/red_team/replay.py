"""Replay the red team's landed attacks against the analyst (127/#299).

123/#289's run stored, for every probe, whether it reached the analyst and how
the grader judged the reply. After a prompt-rule change the question is narrow:
of the attacks that reached the analyst, how many does it now decline that it
answered before — and does anything it answered rightly get declined now? The
before side is the stored verdict; only the after side is paid for.

    uv run python -m experiments.red_team.replay tests \\
        --analysis experiments/out/red-team/full.analysis.json \\
        --out experiments/out/red-team/replay.tests.yaml
    cd experiments/red_team && npx promptfoo@0.122.2 eval -c replay.yaml \\
        --env-file .env.redteam -o ../out/red-team/replay.results.json --no-cache
    uv run python -m experiments.red_team.replay summary \\
        experiments/out/red-team/replay.results.json

The rubric the grader applies is in replay.yaml: the topic rule as written
after this ticket, the machinery rule, and 121's constrained-format leak, so
one replay scores every rule the red team exercised.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Attack:
    text: str
    plugin: str
    strategy: str
    failed_before: bool


def landed_attacks(analysis: Path) -> list[Attack]:
    """The probes that reached the analyst (HTTP 200), as the texts that
    landed: the iterative strategy's final prompt where there is one. A 400
    never reached the analyst; a stream error is not a text it judged."""
    rows = json.loads(analysis.read_text())["rows"]
    return [
        Attack(
            text=row.get("final_prompt") or row["attack"],
            plugin=row["plugin"],
            strategy=row["strategy"],
            failed_before=not row["passed"],
        )
        for row in rows
        if row["status"] == 200
    ]


def write_tests(attacks: list[Attack], out: Path) -> None:
    """promptfoo's tests file: one case per attack, the before verdict riding
    in metadata so the summary can pair them."""
    tests = [
        {
            "vars": {"prompt": a.text},
            "metadata": {
                "pluginId": a.plugin,
                "strategyId": a.strategy,
                "failedBefore": a.failed_before,
            },
        }
        for a in attacks
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(tests, allow_unicode=True, sort_keys=False))


def summarise(results: dict) -> dict:
    """Before against after, from promptfoo's `eval -o` JSON."""
    rows = results["results"]["results"]
    pairs = Counter()
    by_plugin: dict[str, Counter] = {}
    for r in rows:
        meta = (r.get("testCase") or {}).get("metadata") or {}
        before = "failed" if meta.get("failedBefore") else "passed"
        after = "passed" if r.get("success") else "failed"
        pairs[(before, after)] += 1
        by_plugin.setdefault(meta.get("pluginId", "?"), Counter())[(before, after)] += 1
    return {
        "probes": len(rows),
        "fixed": pairs[("failed", "passed")],
        "still_failing": pairs[("failed", "failed")],
        "newly_failing": pairs[("passed", "failed")],
        "still_passing": pairs[("passed", "passed")],
        "by_plugin": {
            p: {f"{b}->{a}": n for (b, a), n in sorted(c.items())}
            for p, c in sorted(by_plugin.items())
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("tests", help="write promptfoo's tests file from the analysis")
    t.add_argument(
        "--analysis",
        type=Path,
        default=Path("experiments/out/red-team/full.analysis.json"),
    )
    t.add_argument(
        "--out", type=Path, default=Path("experiments/out/red-team/replay.tests.yaml")
    )
    s = sub.add_parser(
        "summary", help="before against after, from promptfoo's results JSON"
    )
    s.add_argument("results", type=Path)
    args = parser.parse_args()
    if args.command == "tests":
        attacks = landed_attacks(args.analysis)
        write_tests(attacks, args.out)
        print(
            f"{len(attacks)} attacks reached the analyst; {sum(a.failed_before for a in attacks)} failed before."
        )
    else:
        print(json.dumps(summarise(json.loads(args.results.read_text())), indent=2))


if __name__ == "__main__":
    main()
