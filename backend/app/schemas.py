from pydantic import BaseModel
from typing import Literal


class PanelVoteOutput(BaseModel):
    """One persona's vote as the LLM returns it.

    The model is BLIND to variant identity — it only sees two neutrally
    labelled options in a (counterbalanced) order and picks by position.
    """

    chosen: Literal["option_1", "option_2"]
    reason: str


class VoteRecord(BaseModel):
    """One vote after the system re-attaches identity (what we'd persist).

    `chosen` (a position) is resolved to `chosen_variant_id` using the
    presentation order the system created for this persona.
    """
    persona_id: str
    test_id: str
    chosen_variant_id: str
    presentation_order: list[str]
    reason: str


class Verdict(BaseModel):
    """Naive count verdict for the tracer (no posterior — that's ticket 009)."""
    counts: dict[str, int]
    total: int
    winner: str
