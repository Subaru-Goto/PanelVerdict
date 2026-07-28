import logging
import threading

import pytest

from app.pipeline import EmptyPanel, NoVotes, run_panel_test
from app.persistence import persist_pool
from app.schemas import PanelCounts, RequestedRegion, TargetRequest
from app.vote import VoteResponse
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

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        with self._lock:
            self.calls += 1
        return voted("option_1")


class FailingLLM:
    """Every vote raises, with a message a response body must never carry."""

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
        raise RuntimeError("the model's entire output, which must stay in the log")


class FlakyLLM:
    """The first `failures` votes raise; the rest succeed. Which personas lose their
    vote depends on thread scheduling, and no test here should care."""

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
    is the thing 010a exists to prevent."""
    seed_japanese(conn, 3)

    with (
        caplog.at_level(logging.INFO, logger="app.pipeline"),
        pytest.raises(NoVotes),
    ):
        _run(conn, llm=FailingLLM())

    assert any("usage" in record.message for record in caplog.records)
