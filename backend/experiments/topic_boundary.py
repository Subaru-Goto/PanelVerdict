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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, get_args

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
