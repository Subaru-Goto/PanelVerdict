"""Data contract for the panel pipeline (ticket 002 vote schema).

Three shapes, matching the 002 resolution:
  1. PanelVoteOutput  — what the LLM returns (identity-blind, positional)
  2. VoteRecord       — what the system stores after resolving position -> variant id
  3. Verdict          — the tracer's naive count (no Bayesian yet)
"""


from pydantic import BaseModel


class PanelVoteOutput(BaseModel):
    """One persona's vote as the LLM returns it.

    The model is BLIND to variant identity — it only sees two neutrally
    labelled options in a (counterbalanced) order and picks by position.
    """

    # TODO: chosen — which option did the persona pick?
    #   The model only knows positions, not A/B. Constrain it to exactly the
    #   two positional labels so a malformed value can't slip through.
    #   (hint: Literal["option_1", "option_2"])

    # TODO: reason — a one-line, CONTENT-based rationale (str).
    #   Content-based (not "the first one") so it stays meaningful after we
    #   discard the presentation order.


class VoteRecord(BaseModel):
    """One vote after the system re-attaches identity (what we'd persist).

    `chosen` (a position) is resolved to `chosen_variant_id` using the
    presentation order the system created for this persona.
    """

    # TODO: persona_id (str)
    # TODO: chosen_variant_id (str) — resolved from PanelVoteOutput.chosen
    #       via presentation_order
    # TODO: presentation_order (list[str]) — the variant_ids in the order
    #       shown to this persona; SYSTEM metadata, not model output
    # TODO: reason (str) — carried through from PanelVoteOutput


class Verdict(BaseModel):
    """Naive count verdict for the tracer (no posterior — that's ticket 009)."""

    # TODO: counts (dict[str, int]) — votes per variant_id
    # TODO: total (int) — number of votes counted
    # TODO: winner (str) — variant_id with the most votes
    #   (think: what should happen on a tie? fine to keep it simple for the tracer)