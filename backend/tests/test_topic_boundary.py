"""091/#196 — the topic-boundary suite's deterministic half.

The judged half is paid and lives in `experiments/topic_boundary.py`'s CLI; what
the suite can pin is the case file's shape and the arithmetic over judged rows.
"""

from collections import Counter
from pathlib import Path

from experiments.topic_boundary import CASES_PATH, Case, load_cases

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
    try:
        load_cases(bad)
    except ValueError as error:
        assert "x1" in str(error)
    else:
        raise AssertionError("a bad `expected` value loaded")


def test_a_case_is_immutable_data() -> None:
    case = Case(
        id="r1", question="q", category="report", expected="answer", split="tune"
    )
    try:
        case.question = "changed"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("Case should be frozen")


# --- the judged run's arithmetic, over canned rows -------------------------

import pytest

from experiments.topic_boundary import format_summary, run_cases, score


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

from experiments.topic_boundary import judge_with


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
    judge = judge_with({"answer": answered, "decline": declined})

    passed, reason = await judge(_case("r1", "report", "answer", "tune"), "a reply")
    assert (passed, reason) == (True, "answered says True")
    assert answered.seen == [("q-r1", "a reply")]

    passed, reason = await judge(_case("u1", "unrelated", "decline", "tune"), "nope")
    assert (passed, reason) == (False, "declined says False")
    assert declined.seen == [("q-u1", "nope")]
