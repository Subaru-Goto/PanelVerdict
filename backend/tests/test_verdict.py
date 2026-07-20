from app.schemas import VoteRecord
from app.verdict import tally_votes


def _vote(chosen_variant_id: str) -> VoteRecord:
    """A VoteRecord where only chosen_variant_id matters to the tally."""
    return VoteRecord(
        persona_id="p",
        test_id="t",
        chosen_variant_id=chosen_variant_id,
        presentation_order=["vA", "vB"],
        reason="r",
    )


def test_tally_votes_counts_and_picks_winner() -> None:
    records = [_vote("vA"), _vote("vA"), _vote("vB")]

    verdict = tally_votes(records, variant_ids=["vA", "vB"])

    assert verdict.counts == {"vA": 2, "vB": 1}
    assert verdict.total == 3
    assert verdict.winner == "vA"


def test_tally_votes_zero_fills_variant_with_no_votes() -> None:
    records = [_vote("vA"), _vote("vA")]

    verdict = tally_votes(records, variant_ids=["vA", "vB"])

    assert verdict.counts == {"vA": 2, "vB": 0}  # vB never chosen, still reported
    assert verdict.total == 2
    assert verdict.winner == "vA"


def test_tally_votes_breaks_tie_by_variant_ids_order() -> None:
    # vB is encountered first, but the tiebreak must follow variant_ids order,
    # not the order votes happened to arrive in.
    records = [_vote("vB"), _vote("vA")]

    verdict = tally_votes(records, variant_ids=["vA", "vB"])

    assert verdict.counts == {"vA": 1, "vB": 1}
    assert verdict.winner == "vA"  # tie -> first in variant_ids order
