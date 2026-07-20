from app.schemas import Verdict, VoteRecord


def tally_votes(records: list[VoteRecord], variant_ids: list[str]) -> Verdict:
    """Naive count verdict for the tracer (no posterior — that's 009).

    counts is zero-filled over variant_ids, so a variant that received no
    votes still reports 0. On a tie, winner is the first tied variant in
    variant_ids order — an arbitrary placeholder; modelling real uncertainty
    is 009's job.
    """
    counts = {variant_id: 0 for variant_id in variant_ids}
    for record in records:
        counts[record.chosen_variant_id] += 1
    winner = max(counts, key=counts.get)
    return Verdict(counts=counts, total=len(records), winner=winner)
