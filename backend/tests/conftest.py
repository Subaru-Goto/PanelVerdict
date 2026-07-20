from typing import Literal

import pytest

from app.schemas import PanelVoteOutput


class StubLLM:
    """A PanelLLM double returning a fixed vote for every call — no network."""

    def __init__(self, chosen: Literal["option_1", "option_2"], reason: str = "stub"):
        self._chosen = chosen
        self._reason = reason

    def vote(
        self, *, system_prompt: str, option_1: str, option_2: str
    ) -> PanelVoteOutput:
        return PanelVoteOutput(chosen=self._chosen, reason=self._reason)


@pytest.fixture
def stub_llm() -> type[StubLLM]:
    return StubLLM
