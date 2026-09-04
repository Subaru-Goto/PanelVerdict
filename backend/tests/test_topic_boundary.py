"""091/#196 — the topic-boundary suite's deterministic half.

The judged half is paid and lives in `experiments/topic_boundary.py`'s CLI; what
the suite can pin is the case file's shape and the arithmetic over judged rows.
"""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments.topic_boundary import (
    CASES_PATH,
    Case,
    format_summary,
    judge_with,
    load_cases,
    run_cases,
    score,
    select,
)

IN_SCOPE = {"report", "headlines_general"}
OUT_OF_SCOPE = {"write_headlines", "other_marketing", "unrelated", "disguised"}


def test_the_case_file_covers_every_category_in_both_splits() -> None:
    # Tune on one half, report on the other: a category missing from either
    # split makes the held-out score silent about it.
    cases = load_cases(CASES_PATH)
    by_split_category = Counter((c.split, c.category) for c in cases)
    for category in IN_SCOPE | OUT_OF_SCOPE:
        assert by_split_category[("tune", category)] >= 3, category
        assert by_split_category[("holdout", category)] >= 3, category


def test_expected_behaviour_follows_from_the_category() -> None:
    # The line settled in #196: report questions and headlines-in-general are
    # answered; writing headlines, other marketing, the unrelated and the
    # disguised are declined. A case that says otherwise is a typo in the data.
    for case in load_cases(CASES_PATH):
        expected = "answer" if case.category in IN_SCOPE else "decline"
        assert case.expected == expected, case.id


def test_ids_and_questions_are_unique() -> None:
    cases = load_cases(CASES_PATH)
    assert len({c.id for c in cases}) == len(cases)
    assert len({c.question.strip().lower() for c in cases}) == len(cases)


def test_a_malformed_case_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "cases.json"
    bad.write_text(
        '[{"id": "x1", "question": "q", "category": "report",'
        ' "expected": "maybe", "split": "tune"}]'
    )
    with pytest.raises(ValueError, match="x1"):
        load_cases(bad)


# --- the judged run's arithmetic, over canned rows -------------------------


def _case(id_: str, category: str, expected: str, split: str) -> Case:
    return Case(
        id=id_, question=f"q-{id_}", category=category, expected=expected, split=split
    )


@pytest.mark.anyio
async def test_a_run_records_the_reply_and_the_verdict_per_case() -> None:
    cases = (
        _case("r1", "report", "answer", "tune"),
        _case("u1", "unrelated", "decline", "holdout"),
    )

    async def ask(question: str) -> str:
        return f"reply to {question}"

    async def judge(case: Case, reply: str) -> tuple[bool, str]:
        return (case.id == "r1", f"judged {case.id}")

    rows: list[dict] = []
    await run_cases(cases, ask, judge, rows)

    assert [r["id"] for r in rows] == ["r1", "u1"]
    assert rows[0]["reply"] == "reply to q-r1"
    assert rows[0]["passed"] is True and rows[1]["passed"] is False
    assert rows[1]["reason"] == "judged u1"
    assert rows[1]["split"] == "holdout" and rows[1]["expected"] == "decline"


def test_the_summary_scores_each_split_and_category_separately() -> None:
    rows = [
        {"id": "r1", "category": "report", "split": "tune", "passed": True},
        {"id": "u1", "category": "unrelated", "split": "tune", "passed": False},
        {"id": "u2", "category": "unrelated", "split": "holdout", "passed": True},
        {"id": "d1", "category": "disguised", "split": "holdout", "passed": True},
    ]
    summary = score(rows)
    assert summary["split"]["tune"] == {"n": 2, "passed": 1}
    assert summary["split"]["holdout"] == {"n": 2, "passed": 2}
    assert summary["category"]["unrelated"] == {"n": 2, "passed": 1}

    text = format_summary(rows)
    assert "tune: 1/2" in text
    assert "holdout: 2/2" in text
    assert "unrelated 1/2" in text


# --- the judge: one rubric per expected behaviour ----------------------------


class _FakeMetric:
    """Stands in for a DeepEval metric: `a_measure` sets success and reason."""

    def __init__(self, name: str, success: bool) -> None:
        self.name = name
        self._success = success
        self.success: bool | None = None
        self.reason: str | None = None
        self.seen: list[tuple[str, str]] = []

    async def a_measure(self, test_case) -> float:
        self.seen.append((test_case.input, test_case.actual_output))
        self.success = self._success
        self.reason = f"{self.name} says {self._success}"
        return 1.0 if self._success else 0.0


@pytest.mark.anyio
async def test_the_rubric_is_chosen_by_what_the_case_expects() -> None:
    answered = _FakeMetric("answered", success=True)
    declined = _FakeMetric("declined", success=False)
    judge = judge_with(
        {"answer": answered, "decline": declined},
        lambda question, reply: SimpleNamespace(input=question, actual_output=reply),
    )

    passed, reason = await judge(_case("r1", "report", "answer", "tune"), "a reply")
    assert (passed, reason) == (True, "answered says True")
    assert answered.seen == [("q-r1", "a reply")]

    passed, reason = await judge(_case("u1", "unrelated", "decline", "tune"), "nope")
    assert (passed, reason) == (False, "declined says False")
    assert declined.seen == [("q-u1", "nope")]


def test_a_limited_selection_spreads_across_the_file() -> None:
    # The file is ordered by category, so the first N cases are all one kind;
    # a priced dry run has to exercise both rubrics to price both.
    cases = load_cases(CASES_PATH)
    chosen = select(cases, "tune", 10)
    assert len(chosen) == 10
    assert {c.expected for c in chosen} == {"answer", "decline"}
    assert len({c.category for c in chosen}) >= 4
    assert all(c.split == "tune" for c in chosen)
    assert len(select(cases, "all", None)) == len(cases)


def test_the_red_teams_landed_attacks_are_held_out_cases() -> None:
    """127/#299: the final prompts the analyst answered in the red team
    (chat-red-team.md) join the corpus on the hold-out side, so the run that
    verifies the rule change is scored on the attacks that actually landed.
    Two of the seven are 121's machinery leaks and live with that ticket."""
    cases = {c.id: c for c in load_cases(CASES_PATH)}
    landed = {
        "m25": "other_marketing",  # the GREEN legend
        "d25": "disguised",  # the vividness rubric
        "d26": "disguised",  # the margin as a JavaScript expression
        "w25": "write_headlines",  # the shortest action phrase
        "h25": "headlines_general",  # Less Emails or Fewer Emails: in scope
    }
    for case_id, category in landed.items():
        assert case_id in cases, case_id
        assert cases[case_id].category == category, case_id
        assert cases[case_id].split == "holdout", case_id


def test_named_cases_are_selected_by_id() -> None:
    """Re-running the cases that failed, or the ones a rule change is about,
    should not cost the whole split (127/#299)."""
    cases = load_cases(CASES_PATH)

    chosen = select(cases, "all", None, ids={"w25", "h25"})

    assert [c.id for c in chosen] == ["w25", "h25"]
