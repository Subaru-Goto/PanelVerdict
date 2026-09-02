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
