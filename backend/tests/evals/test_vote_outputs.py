"""The free half of 110/#238: deterministic evaluation, on every push, over the
three committed demo captures — 300 votes a real run bought. No client exists
here by construction: a metric that needs a model call cannot be written in
this directory without one, and that is the point.

DeepEval is the runner. Its `BaseMetric` hosts an assertion as readily as a
judge, which is what the record decided (016, 024): asserts stay asserts, they
just get a suite to live in.
"""

import json
from pathlib import Path

import pytest
from deepeval.evaluate.evaluate import assert_test
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from app.demo import DemoFixture
from app.schemas import PanelVoteOutput

_CAPTURES = sorted(Path("app/data/demo").glob("*.json"))


def _capture(path: Path) -> DemoFixture:
    return DemoFixture.model_validate_json(path.read_text())


# Only every vote validating passes: a share below one is a vote the prompt's
# contract did not hold for, however small the share.
_BAR = 1.0


class EveryVoteIsATypedChoice(BaseMetric):
    """Every recorded vote is the struct the panel prompt asks for, and chose one
    of the two options it was shown — the structured-output validity the ticket
    names. Deterministic: the score is the share of votes that validate, and
    only 1.0 passes."""

    def __init__(self) -> None:
        self.threshold = _BAR
        self.score: float | None = None
        self.reason: str | None = None
        self.success: bool | None = None

    def measure(self, test_case: LLMTestCase) -> float:
        votes = json.loads(str(test_case.actual_output))
        valid = 0
        failures: list[str] = []
        for vote in votes:
            try:
                out = PanelVoteOutput.model_validate(vote)
            except ValueError as error:
                failures.append(f"{vote.get('persona_id', '?')}: {error}")
                continue
            valid += out.chosen in ("option_1", "option_2") and bool(out.reason.strip())
        score = valid / len(votes) if votes else 0.0
        self.score = score
        self.success = score >= _BAR
        self.reason = (
            "every vote validates" if self.success else "; ".join(failures[:3])
        )
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:
        return "Every vote is a typed choice"


@pytest.mark.parametrize("path", _CAPTURES, ids=lambda p: p.stem)
def test_every_captured_vote_is_the_struct_the_prompt_asked_for(path: Path) -> None:
    fixture = _capture(path)
    # The capture keeps the chosen variant; the prompt's own labels are the two
    # positions, so the vote is re-expressed as the model returned it.
    votes = [
        {
            "persona_id": vote.persona_id,
            "chosen": "option_1" if vote.variant == "a" else "option_2",
            "reason": vote.reason,
        }
        for vote in fixture.votes
    ]
    case = LLMTestCase(
        input=f"{fixture.case}: {fixture.size} panelists asked to choose",
        actual_output=json.dumps(votes),
    )

    metrics: list[BaseMetric] = [EveryVoteIsATypedChoice()]
    assert_test(case, metrics, run_async=False)
