from app.schemas import VoteRecord
from app.vote import PanelVotes, VoteFailure, VoteUsage
from experiments.panel_run import latency_percentiles, rows_from_votes


def _usage(seconds: float) -> VoteUsage:
    return VoteUsage(
        input_tokens=270,
        cached_tokens=0,
        output_tokens=234,
        reasoning_tokens=160,
        cost=0.0005,
        seconds=seconds,
    )


def _record(persona_id: str, chosen: str, first: str) -> VoteRecord:
    order = [first, "b" if first == "a" else "a"]
    return VoteRecord(
        persona_id=persona_id,
        test_id="t1",
        chosen_variant_id=chosen,
        presentation_order=order,
        reason="stub",
    )


class TestLatencyPercentiles:
    def test_nearest_rank_on_a_known_series(self) -> None:
        """1..200 seconds: nearest-rank says p50 is the 100th value, p95 the 190th,
        p99 the 198th — a worked example, not a re-derivation of the formula."""
        usage = [_usage(float(s)) for s in range(1, 201)]

        reading = latency_percentiles(usage)

        assert reading is not None
        assert (reading.p50, reading.p95, reading.p99) == (100.0, 190.0, 198.0)
        assert reading.slowest == 200.0

    def test_unreported_usage_is_left_out_not_counted_as_zero(self) -> None:
        """A cached vote's None entry has no latency; folding it in as zero would
        drag every percentile down exactly when the cache makes runs faster."""
        usage = [None, _usage(10.0), None, _usage(20.0)]

        reading = latency_percentiles(usage)

        assert reading is not None
        assert reading.votes_timed == 2
        assert reading.p50 == 10.0

    def test_a_run_with_no_timed_votes_reads_as_absent_not_zero(self) -> None:
        assert latency_percentiles([None, None]) is None
        assert latency_percentiles([]) is None


class TestRowsFromVotes:
    def test_each_vote_becomes_one_row_pairing_choice_with_position(self) -> None:
        """`shown_first` is what makes the 0.66 position-bias readable at scale from
        the raw file — a row that lost the pairing could not be re-analysed."""
        votes = PanelVotes(
            records=[
                _record("p1", chosen="a", first="a"),
                _record("p2", chosen="a", first="b"),
            ],
            usage=(_usage(3.0), None),
            failures=(VoteFailure(persona_id="p3", error="RuntimeError: x"),),
        )

        rows = rows_from_votes("fixed-200", votes)

        assert [(r.persona_id, r.chosen_variant_id, r.shown_first) for r in rows] == [
            ("p1", "a", "a"),
            ("p2", "a", "b"),
            ("p3", None, None),
        ]
        assert rows[0].usage is not None and rows[1].usage is None
        assert rows[2].error == "RuntimeError: x"
        assert all(r.label == "fixed-200" for r in rows)
