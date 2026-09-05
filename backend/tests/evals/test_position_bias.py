"""Position bias, read off recorded votes (110/#238).

The panel prompt shows two neutrally labelled options and the pipeline
counterbalances their order; a model that leans on position picks the
first-shown option more often than the content warrants. The measure is the
first-position rate: the share of votes for whichever option was shown first.
Measured before on paid runs — 0.66 on the retired panel model
(docs/research/manipulation-check.md), 0.42–0.52 on the current one
(docs/research/enacted-context-check.md, "no arm turned into an order effect").

Deterministic and free here: it reads the order the capture recorded, so it
costs nothing on push. The three committed captures predate the field, so they
skip with that reason rather than pass on nothing; the first capture that
carries it turns this on, and the band is set against that measurement rather
than written in advance.
"""

import json
from pathlib import Path

import pytest
from deepeval.evaluate.evaluate import assert_test
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from app.demo import DemoFixture

_CAPTURES = sorted(Path("app/data/demo").glob("*.json"))


class FirstPositionRate(BaseMetric):
    """The share of votes that went to whichever option was shown first.

    Reported, not bounded: `threshold` is None until a capture carrying the
    order exists to set it against (see the module docstring)."""

    def __init__(self) -> None:
        self.threshold = 0.0
        self.score: float | None = None
        self.reason: str | None = None
        self.success: bool | None = None

    def measure(self, test_case: LLMTestCase) -> float:
        votes = json.loads(str(test_case.actual_output))
        first = sum(1 for v in votes if v["chosen"] == v["presentation_order"][0])
        self.score = first / len(votes) if votes else 0.0
        self.success = True
        self.reason = f"{first} of {len(votes)} votes went to the first-shown option"
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    @property
    def __name__(self) -> str:
        return "First-position rate"


@pytest.mark.parametrize("path", _CAPTURES, ids=lambda p: p.stem)
def test_the_first_position_rate_of_a_capture_that_recorded_its_order(
    path: Path,
) -> None:
    fixture = DemoFixture.model_validate_json(path.read_text())
    if any(vote.presentation_order is None for vote in fixture.votes):
        pytest.skip(
            f"{path.name} predates presentation_order; the next capture carries it"
        )
    votes = [
        {"chosen": vote.variant, "presentation_order": vote.presentation_order}
        for vote in fixture.votes
    ]
    case = LLMTestCase(input=fixture.case, actual_output=json.dumps(votes))

    metrics: list[BaseMetric] = [FirstPositionRate()]
    assert_test(case, metrics, run_async=False)
