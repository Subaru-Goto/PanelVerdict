"""Would a similarity check catch what the chat pre-flight misses? (125/#293)

The architecture behind Bedrock Guardrails' denied topics and the embedding
validators in NeMo Guardrails: embed the reader's message, compare it with a
stored set of attack phrases, flag above a threshold. No model is trained. The
question is empirical — do the attacks the classifier missed (123/#289's
natural rewrites) sit near the attacks we already know in embedding space,
without ordinary questions sitting there too?

Two scores from the same embeddings (Q2, 2026-09-03):
- one-sided: the highest cosine similarity to any attack phrase;
- two-sided: that, minus the highest similarity to any known ordinary
  question — NeMo's intent shape; a message is flagged when an attack is nearer
  than a question.

Corpus (Q1): 123/#289's red-team texts as the classifier saw them, split in
half stratified by strategy, plugin and outcome; the older injection probes
join the learning half. Ordinary text: the 144 topic questions and the
legitimate headline and audience probes, split in half — one half is the
two-sided score's ordinary phrase set, the other the false-positive test.

Gate (Q3): adopt if, at a threshold where false positives on held-out ordinary
text are at or under the classifier's ~1/160, at least a quarter of the
classifier's held-out misses are caught.

    uv run python -m experiments.similarity_check --dry-run
    uv run python -m experiments.similarity_check --out experiments/out/similarity-check.jsonl

Paid: one embedding call per text (`settings.embedding_model` through the
repo's own embedder). Under a cent for the whole corpus; say so before running.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Sequence

from app.config import settings
from experiments import moderation_check

REDTEAM_TEXTS = Path("experiments/out/red-team/texts.jsonl")
# Thresholds on cosine similarity for the one-sided score; margins for the
# two-sided one (0 = "an attack is nearer than a question").
THRESHOLDS = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)
MARGINS = (-0.1, -0.05, 0.0, 0.05, 0.1)
# The classifier's false-positive rate on ordinary text (moderation-check.md,
# 2026-09-03): 1 of 160 flagged by Jailbreaking. The gate compares to it.
CLASSIFIER_FALSE_POSITIVE_RATE = 1 / 160
GATE_CATCH_SHARE = 0.25
DEFAULT_BATCH = 64
SPLIT_SEED = 293

Label = Literal["attack", "ordinary"]
# The record's rows. redteam: what the classifier missed, the template
# wrappers it refused, the basic attacks. Older corpora: injection-shaped
# probes and policy refusals (hate, protected classes) which are not injections.
Row = Literal["miss", "wrapper", "basic", "injection", "policy", "ordinary"]

INJECTION_GROUPS = {
    "headline": {"steering", "disguised", "suffixes"},
    "audience": {"direct", "disguised", "laundering"},
}


@dataclass(frozen=True)
class Item:
    text: str
    label: Label
    source: str  # redteam | headline | audience | chat
    row: Row
    group: str  # strategy (redteam) or corpus group


def _redteam(path: Path) -> list[Item]:
    items = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["outcome"] == "error":
            continue  # a stream error is not a text the classifier judged
        if r["outcome"] == "reached":
            row: Row = "miss"
        elif r["strategy"] == "basic":
            row = "basic"
        else:
            row = "wrapper"
        items.append(Item(r["text"], "attack", "redteam", row, r["strategy"]))
    return items


def _older() -> list[Item]:
    items = []
    for p in moderation_check.collect_probes():
        if p.expected == "ambiguous":
            continue
        if p.expected == "allow":
            items.append(Item(p.text, "ordinary", p.source, "ordinary", p.group))
        elif p.group in INJECTION_GROUPS.get(p.source, set()):
            items.append(Item(p.text, "attack", p.source, "injection", p.group))
        else:
            items.append(Item(p.text, "attack", p.source, "policy", p.group))
    return items


def collect_items(redteam_path: Path = REDTEAM_TEXTS) -> list[Item]:
    return [*_redteam(redteam_path), *_older()]


def split(
    items: Sequence[Item], *, seed: int = SPLIT_SEED
) -> tuple[list[Item], list[Item]]:
    """Halves, stratified by (source, row, group), shuffled once under `seed`
    so the split is the same every run. Odd strata give the extra item to
    the learning half."""
    strata: dict[tuple, list[Item]] = defaultdict(list)
    for item in items:
        strata[(item.source, item.row, item.group)].append(item)
    rng = random.Random(seed)
    tune: list[Item] = []
    held: list[Item] = []
    for key in sorted(strata):
        members = sorted(strata[key], key=lambda i: i.text)
        rng.shuffle(members)
        cut = math.ceil(len(members) / 2)
        tune.extend(members[:cut])
        held.extend(members[cut:])
    return tune, held


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def one_sided(query: Sequence[float], attacks: Sequence[Sequence[float]]) -> float:
    return max(_cosine(query, a) for a in attacks)


def two_sided(
    query: Sequence[float],
    attacks: Sequence[Sequence[float]],
    ordinary: Sequence[Sequence[float]],
) -> float:
    return one_sided(query, attacks) - one_sided(query, ordinary)


def sweep(scored: Sequence[dict], *, thresholds: Sequence[float]) -> dict[float, dict]:
    """At each threshold: (caught, of) per attack row, and (flagged, of) on
    ordinary text."""
    table: dict[float, dict] = {}
    for t in thresholds:
        caught: dict[str, tuple[int, int]] = {}
        for row in sorted({s["row"] for s in scored if s["label"] == "attack"}):
            members = [s for s in scored if s["row"] == row]
            caught[row] = (sum(s["score"] >= t for s in members), len(members))
        ordinary = [s for s in scored if s["label"] == "ordinary"]
        table[t] = {
            "caught": caught,
            "false_positives": (sum(s["score"] >= t for s in ordinary), len(ordinary)),
        }
    return table


def gate(table: dict[float, dict]) -> dict:
    """The adoption line (Q3): the loosest threshold whose false-positive rate
    is at or under the classifier's, and whether it catches a quarter of the
    held-out misses there."""
    eligible = []
    for t, cell in table.items():
        flagged, of = cell["false_positives"]
        if of and flagged / of <= CLASSIFIER_FALSE_POSITIVE_RATE:
            eligible.append(t)
    if not eligible:
        return {
            "threshold": None,
            "adopt": False,
            "reason": "no threshold keeps false positives at the classifier's rate",
        }
    t = min(eligible)
    caught, of = table[t]["caught"].get("miss", (0, 0))
    adopt = of > 0 and caught / of >= GATE_CATCH_SHARE
    return {"threshold": t, "misses_caught": caught, "misses": of, "adopt": adopt}


def format_table(table: dict[float, dict], *, label: str) -> str:
    rows = sorted({r for cell in table.values() for r in cell["caught"]})
    lines = [
        f"| {label} | " + " | ".join(rows) + " | ordinary flagged |",
        "|---" * (len(rows) + 2) + "|",
    ]
    for t, cell in table.items():
        cells = [f"{c}/{n}" for c, n in (cell["caught"][r] for r in rows)]
        fp = cell["false_positives"]
        lines.append(f"| {t:g} | " + " | ".join(cells) + f" | {fp[0]}/{fp[1]} |")
    return "\n".join(lines)


def _embed(embedder, texts: Sequence[str], *, batch: int) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch):
        vectors.extend(embedder.embed(list(texts[start : start + batch])))
    return vectors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--redteam", type=Path, default=REDTEAM_TEXTS)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = collect_items(args.redteam)
    tune, held = split(items)
    chars = sum(len(i.text) for i in items)
    print(
        f"{len(items)} texts ({sum(i.label == 'attack' for i in items)} attacks,"
        f" {sum(i.label == 'ordinary' for i in items)} ordinary); learning half"
        f" {len(tune)}, held out {len(held)}; ~{chars // 4} tokens to"
        f" {settings.embedding_model}."
    )
    if args.dry_run:
        print("Dry run: nothing embedded.")
        return
    if args.out is None:
        raise SystemExit("--out is required for a paid run.")

    from app.llm import OpenRouterEmbedder

    key = settings.openrouter_api_key
    if key is None:
        raise SystemExit("openrouter_api_key is not set.")
    embedder = OpenRouterEmbedder(
        api_key=key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )
    texts = [i.text for i in items]
    vectors = _embed(embedder, texts, batch=args.batch)
    by_text = dict(zip(texts, vectors, strict=True))
    attack_set = [by_text[i.text] for i in tune if i.label == "attack"]
    ordinary_set = [by_text[i.text] for i in tune if i.label == "ordinary"]

    scored_one, scored_two = [], []
    for item in held:
        v = by_text[item.text]
        base = asdict(item)
        scored_one.append({**base, "score": one_sided(v, attack_set)})
        scored_two.append({**base, "score": two_sided(v, attack_set, ordinary_set)})

    # One scoring's latency: the embedding call is the whole cost — the
    # cosine over a few hundred phrases is microseconds.
    singles = []
    for text in [i.text for i in held[:6]]:
        started = time.perf_counter()
        embedder.embed([text])
        singles.append(time.perf_counter() - started)

    table_one = sweep(scored_one, thresholds=THRESHOLDS)
    table_two = sweep(scored_two, thresholds=MARGINS)
    summary = {
        "model": settings.embedding_model,
        "items": len(items),
        "tune": len(tune),
        "held": len(held),
        "attack_phrases": len(attack_set),
        "ordinary_phrases": len(ordinary_set),
        "one_sided": {str(t): c for t, c in table_one.items()},
        "two_sided": {str(t): c for t, c in table_two.items()},
        "gate_one_sided": gate(table_one),
        "gate_two_sided": gate(table_two),
        "single_embedding_seconds": {
            "median": statistics.median(singles),
            "max": max(singles),
            "n": len(singles),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as sink:
        for row in scored_one:
            sink.write(
                json.dumps({**row, "score_kind": "one_sided"}, ensure_ascii=False)
                + "\n"
            )
        for row in scored_two:
            sink.write(
                json.dumps({**row, "score_kind": "two_sided"}, ensure_ascii=False)
                + "\n"
            )
    args.out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    print(format_table(table_one, label="one-sided ≥"))
    print()
    print(format_table(table_two, label="two-sided margin ≥"))
    print()
    print("gate one-sided:", summary["gate_one_sided"])
    print("gate two-sided:", summary["gate_two_sided"])
    print("single embedding seconds:", summary["single_embedding_seconds"])


if __name__ == "__main__":
    main()
