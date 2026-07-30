import logging
import threading

import pytest

from app.pipeline import EmptyPanel, NoVotes, run_panel_test
from app.persistence import persist_pool
from app.schemas import PanelCounts, RequestedRegion, TargetRequest
from app.vote import OutOfCredit, VoteResponse
from tests.factories import (
    JAPAN_REQUEST,
    StubTranslator,
    make_assembled,
    make_persona,
    seed_japanese,
    voted,
)


class SpyLLM:
    """Votes option_1 and counts its calls, so a test can assert it was never asked."""

    configuration = "stub"

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        with self._lock:
            self.calls += 1
        return voted("option_1")


class FailingLLM:
    """Every vote raises, with a message a response body must never carry."""

    configuration = "stub"

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        raise RuntimeError("the model's entire output, which must stay in the log")


class FlakyLLM:
    """The first `failures` votes raise; the rest succeed. Which personas lose their
    vote depends on thread scheduling, and no test here should care."""

    configuration = "stub"

    def __init__(self, failures: int) -> None:
        self._remaining = failures
        self._lock = threading.Lock()

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        with self._lock:
            if self._remaining > 0:
                self._remaining -= 1
                raise RuntimeError("transient")
        return voted("option_1")


_ANYONE = TargetRequest()
_NOWHERE = TargetRequest(regions=[RequestedRegion(label="Atlantis")])

_VARIANTS = {"a": "Save 50% today", "b": "Members save half"}


def _run(conn, *, request=JAPAN_REQUEST, size=5, llm=None):
    return run_panel_test(
        conn,
        description="Japanese homeowners",
        variants=_VARIANTS,
        size=size,
        translator=StubTranslator(request),
        llm=llm or SpyLLM(),
    )


def test_a_matched_target_returns_a_verdict_on_the_whole_panel(conn) -> None:
    seed_japanese(conn, 5)

    result = _run(conn)

    assert result.counts == PanelCounts(requested=5, matched=5, voted=5)
    assert result.verdict.share_preferring_b is not None
    assert result.tally.total == 5
    assert len(result.votes.records) == 5


def test_the_verdict_rests_on_the_votes_that_arrived(conn) -> None:
    """The posterior's `total` is `voted`, not `matched`: a verdict computed over the
    drawn panel would count the silent panelists as evidence."""
    seed_japanese(conn, 5)

    result = _run(conn, llm=FlakyLLM(failures=2))

    assert result.counts.matched == 5
    assert result.counts.voted == 3
    assert result.tally.total == 3


def test_a_thin_match_reports_all_three_counts_distinctly(conn) -> None:
    seed_japanese(conn, 2)
    persist_pool(conn, [make_assembled(make_persona(id_="US-00000", country="US"))])

    result = _run(conn, size=5)

    assert result.counts.requested == 5
    assert result.counts.matched == 2
    assert result.counts.voted == 2


def test_notices_survive_assembly(conn) -> None:
    """All three sources in one list: the query's own notice (an unmapped attribute),
    retrieval's (the thin match), and the pipeline's own (failed votes). Dropping any
    of them in assembly is the failure this pins."""
    seed_japanese(conn, 2)
    request = TargetRequest(
        regions=[RequestedRegion(label="Japan", country_code="JP")],
        unmapped=["gamers"],
    )

    result = _run(conn, request=request, size=5, llm=FlakyLLM(failures=1))

    messages = [notice.message for notice in result.notices]
    assert any("gamers" in message for message in messages)
    assert any("Only 2 of the 5" in message for message in messages)
    assert any("1 of the 2" in message for message in messages)


def test_failed_votes_are_a_notice_naming_the_remedy(conn) -> None:
    """The two thinnings read differently because their remedies differ: the pool
    cannot give more matched personas, but a failed vote is transient and a re-run
    may recover it. A customer must not have to subtract counts to learn which gap
    they are looking at."""
    seed_japanese(conn, 5)

    result = _run(conn, llm=FlakyLLM(failures=2))

    (notice,) = [n for n in result.notices if "did not vote" in n.message]
    assert notice.severity == "warning"
    assert "2 of the 5" in notice.message
    assert "re-run" in notice.message


def test_a_full_run_carries_no_vote_notice(conn) -> None:
    seed_japanese(conn, 5)

    result = _run(conn)

    assert not any("did not vote" in n.message for n in result.notices)
    assert result.notices == result.selection.notices


class PrefersLLM:
    """Votes for one headline by content, blind to position — the double that makes
    a lopsided panel deterministic under counterbalanced presentation orders."""

    configuration = "stub"

    def __init__(self, favourite: str) -> None:
        self._favourite = favourite

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        return voted("option_1" if option_1 == self._favourite else "option_2")


def test_a_clear_winner_stops_after_two_confirming_chunks(conn) -> None:
    """Unanimous chunks put P(worth acting on) at ~1.0 from the first boundary,
    but a mid-run stop needs two consecutive confirming boundaries — the streak
    the simulation sourced — so the third chunk is the one never bought."""
    seed_japanese(conn, 75)

    result = _run(conn, size=75, llm=PrefersLLM(_VARIANTS["b"]))

    assert result.stop_reason == "decisive"
    assert result.counts.voted == 50
    assert result.counts.matched == 75
    assert result.tally.total == 50


def test_an_early_stop_reads_as_an_answer_not_a_shortfall(conn) -> None:
    """The sharpest warning about early stopping: stopping because the answer is
    clear and stopping because votes failed are opposite situations with the
    same arithmetic. The
    early stop is a reading; only failures are a warning."""
    seed_japanese(conn, 75)

    result = _run(conn, size=75, llm=PrefersLLM(_VARIANTS["b"]))

    (stopped,) = [n for n in result.notices if "Stopped after" in n.message]
    assert stopped.severity == "reading"
    assert "50 of the 75" in stopped.message
    assert not any("did not vote" in n.message for n in result.notices)


class FlakyPrefersLLM:
    """Prefers one headline by content, but the first `failures` calls raise —
    the double for the trap case where a stop fires with failed votes on board."""

    configuration = "stub"

    def __init__(self, favourite: str, failures: int) -> None:
        self._favourite = favourite
        self._remaining = failures
        self._lock = threading.Lock()

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        with self._lock:
            if self._remaining > 0:
                self._remaining -= 1
                raise RuntimeError("transient")
        return voted("option_1" if option_1 == self._favourite else "option_2")


def test_a_stop_on_the_last_chunk_with_failures_is_not_an_early_stop(conn) -> None:
    """The trap the first version fell into: a decision firing on the final
    boundary with a few failed votes left nobody unasked, so "the remaining votes
    would not have changed the call" would be a false sentence about votes that
    merely failed. No stopped notice — the failures keep their own warning."""
    seed_japanese(conn, 50)

    result = _run(conn, size=50, llm=FlakyPrefersLLM(_VARIANTS["b"], failures=2))

    assert result.stop_reason == "decisive"
    assert result.counts.voted == 48
    assert not any("Stopped after" in n.message for n in result.notices)
    assert any("2 of the 50" in n.message for n in result.notices)


def test_an_undecided_run_buys_the_whole_panel(conn) -> None:
    """Counterbalanced orders under a position-only voter split near even, and an
    even split at n=50 proves nothing — so every chunk is bought and no stopped
    notice appears."""
    seed_japanese(conn, 50)

    result = _run(conn, size=50)

    assert result.stop_reason is None
    assert result.counts.voted == 50
    assert not any("Stopped after" in n.message for n in result.notices)


def test_coverage_travels_as_data(conn) -> None:
    """The ticket's sharpest case: a target that named nowhere and one that named
    somewhere unservable resolve to the identical country tuple, and only `coverage`
    tells a reader which panel they are looking at."""
    seed_japanese(conn, 5)

    served = _run(conn, request=_ANYONE)
    substituted = _run(conn, request=_NOWHERE)

    assert served.selection.query.countries == substituted.selection.query.countries
    assert served.selection.query.coverage == "requested"
    assert substituted.selection.query.coverage == "unmatched"


def test_an_empty_panel_is_refused_before_any_vote_is_paid_for(conn) -> None:
    persist_pool(conn, [make_assembled(make_persona(id_="US-00000", country="US"))])
    llm = SpyLLM()

    with pytest.raises(EmptyPanel):
        _run(conn, llm=llm)

    assert llm.calls == 0


def test_a_panel_with_no_votes_is_refused_with_types_not_messages(conn) -> None:
    seed_japanese(conn, 3)

    with pytest.raises(NoVotes) as excinfo:
        _run(conn, llm=FailingLLM())

    assert "RuntimeError" in str(excinfo.value)
    assert "entire output" not in str(excinfo.value)


def test_usage_is_logged_even_when_no_verdict_comes_out(conn, caplog) -> None:
    """The refusal path still paid for its failures' retries and for nothing else —
    but the log line must exist either way, because a run whose cost is unrecoverable
    is the thing this instrumentation exists to prevent."""
    seed_japanese(conn, 3)

    with (
        caplog.at_level(logging.INFO, logger="app.pipeline"),
        pytest.raises(NoVotes),
    ):
        _run(conn, llm=FailingLLM())

    assert any("usage" in record.message for record in caplog.records)


def test_the_run_records_its_own_wall_time(conn, caplog) -> None:
    """The one figure no per-vote number can give. Votes fan out concurrently,
    so their seconds do not add up to the run's; and only the wall clock says
    whether a slow run was one straggler holding its wave or every vote being
    slow at once. Without it a "why was that slow" question has no evidence
    but guesswork."""
    seed_japanese(conn, 3)

    with caplog.at_level(logging.INFO, logger="app.pipeline"):
        _run(conn)

    (line,) = [r.message for r in caplog.records if "panel usage" in r.message]
    assert "wall=" in line
    assert "seconds_slowest" in line


class TestVoteCache:
    """Every vote is stored keyed on the fingerprint of the question asked,
    and the ledger is read before the model is — a re-run replays, a broken run
    resumes, and nothing downstream can tell a cached vote from a paid one."""

    def test_a_re_run_replays_the_whole_test_without_paying(self, conn) -> None:
        seed_japanese(conn, 5)
        first = _run(conn)

        spy = SpyLLM()
        second = _run(conn, llm=spy)

        assert spy.calls == 0
        # Record equality includes test_id: a cached vote keeps the id of the run
        # that paid for it — provenance, not this run's correlation id.
        assert second.votes.records == first.votes.records
        assert second.verdict == first.verdict

    def test_a_resumed_run_pays_only_for_the_votes_that_failed(self, conn) -> None:
        seed_japanese(conn, 5)
        first = _run(conn, llm=FlakyLLM(failures=2))
        assert len(first.votes.records) == 3

        spy = SpyLLM()
        second = _run(conn, llm=spy)

        assert spy.calls == 2
        assert len(second.votes.records) == 5
        assert second.votes.failures == ()
        # Usage stays parallel to records — None per cached vote — and the cached
        # three sit among the five in panel order, exactly as first cast.
        assert len(second.votes.usage) == 5
        cached = {r.persona_id for r in first.votes.records}
        assert [
            r for r in second.votes.records if r.persona_id in cached
        ] == first.votes.records

    def test_a_changed_headline_is_a_new_question(self, conn) -> None:
        seed_japanese(conn, 5)
        _run(conn)

        spy = SpyLLM()
        run_panel_test(
            conn,
            description="Japanese homeowners",
            variants=_VARIANTS | {"b": "A different promise"},
            size=5,
            translator=StubTranslator(),
            llm=spy,
        )

        assert spy.calls == 5

    def test_paid_votes_survive_the_run_dying_before_the_response(self, conn) -> None:
        """The ledger's whole point: a run that dies at vote 180 must not cost 180
        votes to get back. The request connection only commits at a clean exit, so
        a store that waits for it dies with the run — votes must be committed per
        chunk, and a rollback (what a crashed request leaves behind) must not
        take them."""
        seed_japanese(conn, 5)
        _run(conn)
        conn.rollback()

        spy = SpyLLM()
        _run(conn, llm=spy)

        assert spy.calls == 0


class OutOfCreditLLM:
    """Answers the first `paid` votes, then every call is the provider's 402.

    Counts calls so a test can assert the pipeline stopped *asking* — fanning out
    chunk after chunk of doomed requests costs latency, and the panelists' order
    means later chunks would all fail anyway.
    """

    configuration = "stub"

    def __init__(self, paid: int) -> None:
        self.calls = 0
        self._paid = paid
        self._lock = threading.Lock()

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        with self._lock:
            self.calls += 1
            if self.calls <= self._paid:
                return voted("option_1")
        raise OutOfCredit("OpenRouter credit exhausted (402)")


class TestOutOfCredit:
    """A mid-run 402 is terminal for the run but not for the test — the cache
    holds what was paid for, so the stop's message is 'top up and resume', and the
    endpoint's code says whose fault it is (the account's, not the server's)."""

    def test_credit_running_out_mid_run_stops_asking_and_names_the_remedy(
        self, conn
    ) -> None:
        # Seeded with 75 *distinct* ages, not seed_japanese (which wraps at 60):
        # the prompt omits the persona id, so age-twins render identical prompts,
        # fingerprint identically, and share cached votes across chunks — content
        # is identity, and this test needs 75 distinguishable panelists.
        persist_pool(
            conn,
            [
                make_assembled(
                    make_persona(id_=f"JP-{i:05d}", country="JP", age=20 + i)
                )
                for i in range(75)
            ],
        )
        llm = OutOfCreditLLM(paid=25)

        result = _run(conn, size=75, llm=llm)

        assert result.counts.voted == 25
        # Chunk 3 was never attempted: 25 paid + 25 refused, not 75.
        assert llm.calls == 50
        (notice,) = [n for n in result.notices if "credit" in n.message.lower()]
        assert notice.severity == "warning"
        assert "25" in notice.message and "75" in notice.message
        assert "top up" in notice.message and "re-run" in notice.message

    def test_the_saved_votes_actually_resume(self, conn) -> None:
        seed_japanese(conn, 50)
        _run(conn, size=50, llm=OutOfCreditLLM(paid=25))

        spy = SpyLLM()
        result = _run(conn, size=50, llm=spy)

        assert result.counts.voted == 50
        assert spy.calls == 25

    def test_no_votes_and_no_credit_raises_out_of_credit_not_no_votes(
        self, conn
    ) -> None:
        seed_japanese(conn, 5)

        with pytest.raises(OutOfCredit):
            _run(conn, llm=OutOfCreditLLM(paid=0))

    def test_a_partially_paid_chunk_keeps_its_votes_and_tells_one_story(
        self, conn
    ) -> None:
        """The credit can die mid-chunk: the paid votes in that chunk must survive,
        and the 402 refusals must not also be narrated as 'transient' vote failures
        — 'a re-run may recover them' and 'credit ran out' beside each other read
        as a contradiction, and the credit notice already names the real remedy."""
        persist_pool(
            conn,
            [
                make_assembled(
                    make_persona(id_=f"JP-{i:05d}", country="JP", age=20 + i)
                )
                for i in range(75)
            ],
        )
        llm = OutOfCreditLLM(paid=30)

        result = _run(conn, size=75, llm=llm)

        assert result.counts.voted == 30
        assert llm.calls == 50
        (credit,) = [n for n in result.notices if "credit" in n.message.lower()]
        assert "30" in credit.message
        assert not any("did not vote" in n.message for n in result.notices)
