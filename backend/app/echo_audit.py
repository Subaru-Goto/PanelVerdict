"""Measure how strongly persisted interests echo their prompt examples.

Run: python -m app.echo_audit --size dev|full --seed N [--countries US,JP,DE]

Read-only diagnostic for the example-bank design: the bank shapes the pool only
through the model's suggestibility, so this measures that coupling — echo rate
(interests matching the persona's own prompted examples), in-bank rate, and the
top interest frequencies (the monoculture check). Examples are recomputed from
the seed, not stored: same master seed + slot -> same draw. Ids are generated
from quotas and matched against the DB, never parsed.
"""

import argparse
from collections import Counter
from dataclasses import dataclass

import psycopg

from app.assembly import persona_id, prompt_examples_for_slot
from app.config import settings
from app.hobbies import load_hobby_bank
from app.seed import add_pool_args, build_quotas

_TOP_N = 20


@dataclass(frozen=True)
class EchoReport:
    expected: int
    found: int
    interests_total: int
    echo_rate: float
    in_bank_rate: float
    top: list[tuple[str, int]]


def compute_echo(
    interests_by_id: dict[str, list[str]],
    examples_by_id: dict[str, list[str]],
    bank_by_id: dict[str, frozenset[str]],
) -> EchoReport:
    """Exact casefolded matching, so the measured echo is a lower bound —
    a paraphrase ("fly fishing" from "fishing") does not count."""
    counts: Counter[str] = Counter()
    total = echoed = in_bank = 0
    for pid, interests in interests_by_id.items():
        examples = {e.casefold() for e in examples_by_id[pid]}
        bank = {b.casefold() for b in bank_by_id[pid]}
        for interest in interests:
            key = interest.casefold()
            counts[key] += 1
            total += 1
            echoed += key in examples
            in_bank += key in bank
    return EchoReport(
        expected=len(examples_by_id),
        found=len(interests_by_id),
        interests_total=total,
        echo_rate=echoed / total if total else 0.0,
        in_bank_rate=in_bank / total if total else 0.0,
        top=counts.most_common(_TOP_N),
    )


def format_echo_report(report: EchoReport) -> str:
    lines = [
        "=== Echo audit ===",
        f"Personas: {report.found} found of {report.expected} expected, "
        f"interests: {report.interests_total}",
    ]
    if report.found != report.expected:
        lines.append(
            "WARNING: expected personas without rows — rates below cover only the "
            "found subset; check --size/--seed/--countries match the seeded pool."
        )
    lines += [
        f"Echo rate (interest = own prompt example): {report.echo_rate:.2f}",
        f"In-bank rate (interest anywhere in country bank): {report.in_bank_rate:.2f}",
        f"Top {len(report.top)} interests:",
    ]
    lines += [f"  {count:4d}  {interest}" for interest, count in report.top]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_pool_args(parser)
    args = parser.parse_args()

    examples_by_id: dict[str, list[str]] = {}
    bank_by_id: dict[str, frozenset[str]] = {}
    for country, n in build_quotas(args.size, args.countries).items():
        bank = load_hobby_bank(country)
        bank_set = frozenset(bank.common + bank.niche)
        for index in range(n):
            pid = persona_id(country, index)
            examples_by_id[pid] = prompt_examples_for_slot(
                country, index, bank, master_seed=args.seed
            )
            bank_by_id[pid] = bank_set

    interests_by_id: dict[str, list[str]] = {}
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            "SELECT persona_id, interest FROM interests WHERE persona_id = ANY(%s)",
            (list(examples_by_id),),
        )
        for pid, interest in rows:
            interests_by_id.setdefault(pid, []).append(interest)

    print(format_echo_report(compute_echo(interests_by_id, examples_by_id, bank_by_id)))


if __name__ == "__main__":
    main()
