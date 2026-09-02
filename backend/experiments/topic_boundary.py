"""Does the analyst hold its subject? (091/#196)

The prompt now names the analyst's subject — this test, and how headlines
perform in general — and a fixed shape for declining everything else. Prompt
obedience cannot be asserted by the suite, whose doubles route the model, so it
is measured here: every case in `topic_boundary_cases.json` is asked of the real
analyst, and a judge scores the reply against the shape the ticket settled.

The cases are hand-written and split in two. The `tune` half is what the prompt
wording may be adjusted against; the `holdout` half is scored once the wording
is fixed and is the number that goes in the research note. Tuning against the
half you report on measures the fit to those questions, not the boundary.

    python -m experiments.topic_boundary --split holdout \\
        --out experiments/out/topic-boundary-holdout.jsonl

`--limit 10` is the dry run that prices a case before the full set is spent.
"""

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

Category = Literal[
    "report",
    "headlines_general",
    "write_headlines",
    "other_marketing",
    "unrelated",
    "disguised",
]
Expected = Literal["answer", "decline"]
Split = Literal["tune", "holdout"]

CASES_PATH = Path(__file__).with_name("topic_boundary_cases.json")


@dataclass(frozen=True)
class Case:
    id: str
    question: str
    category: Category
    expected: Expected
    split: Split


def load_cases(path: Path) -> tuple[Case, ...]:
    """Read the case file, refusing any row whose fields are outside the schema.

    Named in the error so a typo in a hundred-row file is found by id, not by
    re-reading the file.
    """
    rows = json.loads(path.read_text())
    cases: list[Case] = []
    for row in rows:
        case_id = str(row.get("id", "?"))
        for field, allowed in (
            ("category", get_args(Category)),
            ("expected", get_args(Expected)),
            ("split", get_args(Split)),
        ):
            if row.get(field) not in allowed:
                raise ValueError(
                    f"case {case_id}: {field}={row.get(field)!r} not in {allowed}"
                )
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError(f"case {case_id}: question is empty")
        cases.append(
            Case(
                id=case_id,
                question=row["question"],
                category=row["category"],
                expected=row["expected"],
                split=row["split"],
            )
        )
    return tuple(cases)


Ask = Callable[[str], Awaitable[str]]
Judge = Callable[[Case, str], Awaitable[tuple[bool, str]]]


async def run_cases(
    cases: Sequence[Case], ask: Ask, judge: Judge, rows: list[dict]
) -> None:
    """Ask every case of the analyst, judge the reply, append one row per case.

    Appends into the caller's list, as `corpus_check` does: every case is two
    paid calls, and a 429 on the last one must not cost the rows before it.
    """
    for case in cases:
        reply = await ask(case.question)
        passed, reason = await judge(case, reply)
        rows.append(
            {
                "id": case.id,
                "category": case.category,
                "expected": case.expected,
                "split": case.split,
                "question": case.question,
                "reply": reply,
                "passed": passed,
                "reason": reason,
            }
        )


def score(rows: Sequence[dict]) -> dict[str, dict[str, dict[str, int]]]:
    """Passed-over-n by split and by category; the split figure is the one reported."""
    summary: dict[str, dict[str, dict[str, int]]] = {"split": {}, "category": {}}
    for row in rows:
        for axis in ("split", "category"):
            bucket = summary[axis].setdefault(row[axis], {"n": 0, "passed": 0})
            bucket["n"] += 1
            bucket["passed"] += int(bool(row["passed"]))
    return summary


def format_summary(rows: Sequence[dict]) -> str:
    summary = score(rows)
    lines = [
        f"{split}: {b['passed']}/{b['n']} passed"
        for split, b in sorted(summary["split"].items())
    ]
    lines.append(
        "by category: "
        + ", ".join(
            f"{category} {b['passed']}/{b['n']}"
            for category, b in sorted(summary["category"].items())
        )
    )
    return "\n".join(lines)


class Measures(Protocol):
    """The slice of a DeepEval metric this runner uses — so a test can fake it."""

    success: bool | None
    reason: str | None

    async def a_measure(self, test_case: Any) -> float: ...


def judge_with(metrics: Mapping[Expected, Measures]) -> Judge:
    """One rubric per expected behaviour: the case says which one applies.

    A declined case is judged on the shape the ticket settled (outside what it
    covers, then what it can help with, no partial answer first); an answered
    case on having been taken as in scope. Scoring both against one rubric
    would let "declined everything" pass the whole file.
    """
    from deepeval.test_case import LLMTestCase

    async def judge(case: Case, reply: str) -> tuple[bool, str]:
        metric = metrics[case.expected]
        await metric.a_measure(LLMTestCase(input=case.question, actual_output=reply))
        return bool(metric.success), metric.reason or ""

    return judge
