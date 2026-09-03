"""Run the repo's probe sets through Mistral's moderation classifier (120/#279).

The chat message is not screened, and the deferral rested on a second model call
per turn. A hosted classifier has neither the latency nor the cost of one, so
before adopting it two numbers are owed: how many of the injection probes its
*Jailbreaking* category catches, and how often any category fires on ordinary
text — headlines are imperatives, the documented weak spot of such classifiers.

Probes are the corpora that already exist: `headline_guard` (copy, steering,
disguised, suffixes), `roleplay_guard` (audience descriptions) and the
`topic_boundary` questions, which are never injections — an off-topic question
is the analyst's to decline, not a classifier's to block.

    cd backend && python -m experiments.moderation_check --dry-run
    cd backend && python -m experiments.moderation_check \\
        --out experiments/out/moderation-check.jsonl

Free at the listed price; the request count is printed. The reply is read by its
own category keys, so a category the docs add or drop changes nothing here.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx

from app.config import settings
from experiments import headline_guard, roleplay_guard, topic_boundary

Source = Literal["headline", "audience", "chat"]
Expected = Literal["allow", "refuse", "ambiguous"]

MODERATE_PATH = "/moderations"
TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Probe:
    source: Source
    id: str
    expected: Expected
    text: str
    group: str


def _headlines() -> list[Probe]:
    groups = (
        ("copy", headline_guard.COPY),
        ("steering", headline_guard.STEERING),
        ("disguised", headline_guard.DISGUISED),
        ("suffix", headline_guard.SUFFIXES),
    )
    return [
        Probe("headline", h.id, h.expected, h.text, group)
        for group, headlines in groups
        for h in headlines
    ]


def _audiences() -> list[Probe]:
    # A refusal class names why the generator refuses; for a classifier that
    # only says "attack or not", every refusal class is one expectation.
    def expected(verdict: str) -> Expected:
        return verdict if verdict in ("allow", "ambiguous") else "refuse"

    groups = (
        ("legitimate", roleplay_guard.LEGITIMATE),
        ("direct", roleplay_guard.DIRECT),
        ("disguised", roleplay_guard.DISGUISED),
        ("laundering", roleplay_guard.LAUNDERING),
        ("protected", roleplay_guard.PROTECTED),
        ("named", roleplay_guard.NAMED),
        ("not_audience", roleplay_guard.NOT_AUDIENCE),
        ("harmful", roleplay_guard.HARMFUL),
        ("ambiguous", roleplay_guard.AMBIGUOUS),
    )
    return [
        Probe("audience", p.id, expected(p.expected), p.words, group)
        for group, probes in groups
        for p in probes
    ]


def _questions() -> list[Probe]:
    return [
        Probe("chat", case.id, "allow", case.question, case.category)
        for case in topic_boundary.load_cases(topic_boundary.CASES_PATH)
    ]


def collect_probes() -> tuple[Probe, ...]:
    return (*_headlines(), *_audiences(), *_questions())


def moderate(
    client: httpx.Client,
    probes: Sequence[Probe],
    *,
    model: str,
    api_key: str,
    batch: int,
) -> list[dict]:
    """One row per probe, in order: the classifier's flags and scores by its own keys.

    Body and reply shape from Mistral's OpenAPI file (`platform-docs-public`,
    read 2026-09-03): `POST /v1/moderations` with `model` and `input` (a list),
    `results[i].categories` (booleans) and `results[i].category_scores`.
    """
    rows: list[dict] = []
    headers = {"Authorization": f"Bearer {api_key}"}
    for start in range(0, len(probes), batch):
        chunk = probes[start : start + batch]
        response = client.post(
            MODERATE_PATH,
            json={"model": model, "input": [p.text for p in chunk]},
            headers=headers,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        results = response.json()["results"]
        if len(results) != len(chunk):
            raise RuntimeError(f"{len(chunk)} inputs, {len(results)} results")
        for probe, result in zip(chunk, results, strict=True):
            rows.append(
                {
                    **asdict(probe),
                    "flagged": result["categories"],
                    "scores": result["category_scores"],
                }
            )
    return rows


def summarise(rows: Sequence[dict]) -> dict[str, dict[str, dict[str, dict[str, int]]]]:
    """expected → source → category → {flagged, of}.

    Read two ways: under `refuse`, `jailbreaking.flagged/of` is the catch rate on
    attacks; under `allow`, any category's `flagged` is a false positive for this
    product. `ambiguous` is reported, not scored.
    """
    summary: dict[str, dict[str, dict[str, dict[str, int]]]] = {}
    for row in rows:
        by_category = summary.setdefault(row["expected"], {}).setdefault(
            row["source"], {}
        )
        for category, hit in row["flagged"].items():
            cell = by_category.setdefault(category, {"flagged": 0, "of": 0})
            cell["of"] += 1
            cell["flagged"] += int(bool(hit))
    return summary


def format_summary(summary: dict) -> str:
    lines: list[str] = []
    for expected, label in (
        ("refuse", "attacks — caught by"),
        ("allow", "ordinary text — false positives by"),
        ("ambiguous", "ambiguous — fired by"),
    ):
        for source, by_category in sorted(summary.get(expected, {}).items()):
            fired = {
                c: v
                for c, v in by_category.items()
                if v["flagged"] or c == "jailbreaking"
            }
            cells = ", ".join(
                f"{c} {v['flagged']}/{v['of']}" for c, v in sorted(fired.items())
            )
            lines.append(f"{expected:9} {source:9} {label}: {cells or 'nothing'}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    probes = collect_probes()
    requests = -(-len(probes) // args.batch)
    print(
        f"{len(probes)} probes in {requests} requests to {settings.moderation_model}."
    )
    if args.dry_run:
        return
    if args.out is None:
        raise SystemExit("--out is required for a live run.")
    if settings.mistral_api_key is None:
        raise SystemExit("mistral_api_key is not set.")

    with httpx.Client(base_url=settings.mistral_base_url) as client:
        rows = moderate(
            client,
            probes,
            model=settings.moderation_model,
            api_key=settings.mistral_api_key.get_secret_value(),
            batch=args.batch,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as sink:
        for row in rows:
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(format_summary(summarise(rows)))
    print(f"rows: {args.out}")


if __name__ == "__main__":
    main()
