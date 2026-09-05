import asyncio
import logging
import threading
import time

import pytest
from psycopg.pq import TransactionStatus

from app import pipeline
from app.config import PROFILES
from app.persistence import persist_pool
from app.pipeline import EmptyPanel, NoVotes, run_panel_test, run_vote_loop
from app.schemas import PanelCounts, RequestedRegion, TargetRequest
from app.targeting import select_panel
from app.verdict import stopping_decision
from app.vote import VOTE_CONCURRENCY, OutOfCredit, VoteResponse
from tests.factories import (
    JAPAN_REQUEST,
    StubTranslator,
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

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        with self._lock:
            self.calls += 1
        return voted("option_1")


class FailingLLM:
    """Every vote raises, with a message a response body must never carry."""

    configuration = "stub"

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        raise RuntimeError("the model's entire output, which must stay in the log")


class FlakyLLM:
    """The first `failures` votes raise; the rest succeed. Which personas lose their
    vote depends on thread scheduling, and no test here should care."""

    configuration = "stub"

    def __init__(self, failures: int) -> None:
        self._remaining = failures
        self._lock = threading.Lock()

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        with self._lock:
            if self._remaining > 0:
                self._remaining -= 1
                raise RuntimeError("transient")
        return voted("option_1")


_ANYONE = TargetRequest()
_NOWHERE = TargetRequest(regions=[RequestedRegion(label="Atlantis")])

_VARIANTS = {"a": "Save 50% today", "b": "Members save half"}


async def _run(aconn, *, request=JAPAN_REQUEST, size=5, llm=None):
    return await run_panel_test(
        aconn,
        description="Japanese homeowners",
        variants=_VARIANTS,
        size=size,
        translator=StubTranslator(request),
        llm=llm or SpyLLM(),
    )


@pytest.mark.anyio
async def test_a_matched_target_returns_a_verdict_on_the_whole_panel(
    conn, aconn
) -> None:
    seed_japanese(conn, 5)

    result = await _run(aconn)

    assert result.counts == PanelCounts(requested=5, matched=5, voted=5)
    assert result.verdict.share_preferring_b is not None
    assert result.tally.total == 5
    assert len(result.votes.records) == 5


@pytest.mark.anyio
async def test_the_paid_wave_runs_with_no_transaction_open(conn, aconn) -> None:
    """113/#243: `load_votes` opened a transaction and the whole model wave
    then ran inside `asyncio.to_thread` with the connection idle-in-transaction
    — a session killed there returns paid votes with no connection to record
    them on, the exact loss the per-chunk ledger exists to prevent (the full
    why lives with the commit in `_chunk_votes`). The read commits before the
    wave, so the connection waits idle instead — observed from inside the
    wave, by the votes themselves.
    """
    seed_japanese(conn, 5)
    seen: list[TransactionStatus] = []

    class ProbingLLM(SpyLLM):
        def vote(self, **kwargs) -> VoteResponse:
            with self._lock:
                seen.append(aconn.info.transaction_status)
            return super().vote(**kwargs)

    await _run(aconn, llm=ProbingLLM())

    assert seen, "the panel never voted, so nothing was probed"
    assert set(seen) == {TransactionStatus.IDLE}


@pytest.mark.anyio
async def test_the_verdict_rests_on_the_votes_that_arrived(conn, aconn) -> None:
    """The posterior's `total` is `voted`, not `matched`: a verdict computed over the
    drawn panel would count the silent panelists as evidence."""
    seed_japanese(conn, 5)

    result = await _run(aconn, llm=FlakyLLM(failures=2))

    assert result.counts.matched == 5
    assert result.counts.voted == 3
    assert result.tally.total == 3


@pytest.mark.anyio
async def test_a_thin_match_reports_all_three_counts_distinctly(conn, aconn) -> None:
    seed_japanese(conn, 2)
    persist_pool(conn, [make_persona(id_="US-00000", country="US")])

    result = await _run(aconn, size=5)

    assert result.counts.requested == 5
    assert result.counts.matched == 2
    assert result.counts.voted == 2


@pytest.mark.anyio
async def test_notices_survive_assembly(conn, aconn) -> None:
    """All three sources in one list: the query's own notice (an unmapped attribute),
    retrieval's (the thin match), and the pipeline's own (failed votes). Dropping any
    of them in assembly is the failure this pins."""
    seed_japanese(conn, 2)
    request = TargetRequest(
        regions=[RequestedRegion(label="Japan", country_code="JP")],
        unmapped=["gamers"],
    )

    result = await _run(aconn, request=request, size=5, llm=FlakyLLM(failures=1))

    messages = [notice.message for notice in result.notices]
    assert any("gamers" in message for message in messages)
    assert any("Only 2 of the 5" in message for message in messages)
    assert any("1 of the 2" in message for message in messages)


@pytest.mark.anyio
async def test_failed_votes_are_a_notice_naming_the_remedy(conn, aconn) -> None:
    """The two thinnings read differently because their remedies differ: the pool
    cannot give more matched personas, but a failed vote is transient and a re-run
    may recover it. A customer must not have to subtract counts to learn which gap
    they are looking at."""
    seed_japanese(conn, 5)

    result = await _run(aconn, llm=FlakyLLM(failures=2))

    (notice,) = [n for n in result.notices if "did not vote" in n.message]
    assert notice.severity == "warning"
    assert "2 of the 5" in notice.message
    assert "re-run" in notice.message


@pytest.mark.anyio
async def test_a_full_run_carries_no_vote_notice(conn, aconn) -> None:
    seed_japanese(conn, 5)

    result = await _run(aconn)

    assert not any("did not vote" in n.message for n in result.notices)
    assert result.notices == result.selection.notices


class PrefersLLM:
    """Votes for one headline by content, blind to position — the double that makes
    a lopsided panel deterministic under counterbalanced presentation orders."""

    configuration = "stub"

    def __init__(self, favourite: str) -> None:
        self._favourite = favourite

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        return voted("option_1" if option_1 == self._favourite else "option_2")


@pytest.mark.anyio
async def test_a_clear_winner_stops_after_two_confirming_chunks(conn, aconn) -> None:
    """Unanimous chunks put P(worth acting on) at ~1.0 from the first boundary,
    but a mid-run stop needs two consecutive confirming boundaries — the streak
    the simulation sourced — so the third chunk is the one never bought."""
    seed_japanese(conn, 75)

    result = await _run(aconn, size=75, llm=PrefersLLM(_VARIANTS["b"]))

    assert result.stop_reason == "decisive"
    assert result.counts.voted == 50
    assert result.counts.matched == 75
    assert result.tally.total == 50


@pytest.mark.anyio
async def test_the_stop_cannot_fire_on_a_panel_of_one_chunk(conn, aconn) -> None:
    """042/#140: the chunk is one concurrency-load, so a panel the size of the
    cap is a single fan-out with a single boundary — and a streak of one never
    reaches the two confirmations the stop needs. The dev profile is exactly
    that size, so a landslide there runs to the cap; a dev run that "went to
    the cap" is not a stop that misfired."""
    seed_japanese(conn, VOTE_CONCURRENCY)

    result = await _run(aconn, size=VOTE_CONCURRENCY, llm=PrefersLLM(_VARIANTS["b"]))

    assert result.stop_reason is None
    # The streak is what withheld the stop, not the reading: this one boundary
    # read decisive, and one confirmation is never two.
    assert (
        stopping_decision(
            preferring_b=result.tally.counts["b"], total=result.tally.total
        )
        == "decisive"
    )


def test_the_decisive_floor_sits_above_dev_and_halfway_through_demo() -> None:
    """The earliest a decisive run can stop is confirmations × chunk. 50 is not
    arithmetic here: docs/research/first-full-scale-run.md records the `stopped`
    run ending at exactly 50 of 200 votes, "`decisive` at the 2-chunk floor".
    Pinned against the real profiles too, so a change to either constant or to a
    profile size has to come back here and say what it did to the floor."""
    floor = pipeline._STOP_CONFIRMATIONS * VOTE_CONCURRENCY

    assert floor == 50, "the floor the recorded run stopped at"
    assert PROFILES["dev"].size < floor, "dev cannot stop early at all"
    assert PROFILES["demo"].size == 2 * floor, "demo leaves at most half unbought"
    assert PROFILES["prod"].size == 4 * floor, "prod at most three quarters"


@pytest.mark.anyio
async def test_an_early_stop_reads_as_an_answer_not_a_shortfall(conn, aconn) -> None:
    """The sharpest warning about early stopping: stopping because the answer is
    clear and stopping because votes failed are opposite situations with the
    same arithmetic. The
    early stop is a reading; only failures are a warning."""
    seed_japanese(conn, 75)

    result = await _run(aconn, size=75, llm=PrefersLLM(_VARIANTS["b"]))

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

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        with self._lock:
            if self._remaining > 0:
                self._remaining -= 1
                raise RuntimeError("transient")
        return voted("option_1" if option_1 == self._favourite else "option_2")


@pytest.mark.anyio
async def test_a_stop_on_the_last_chunk_with_failures_is_not_an_early_stop(
    conn, aconn
) -> None:
    """The trap the first version fell into: a decision firing on the final
    boundary with a few failed votes left nobody unasked, so "the remaining votes
    would not have changed the call" would be a false sentence about votes that
    merely failed. No stopped notice — the failures keep their own warning."""
    seed_japanese(conn, 50)

    result = await _run(aconn, size=50, llm=FlakyPrefersLLM(_VARIANTS["b"], failures=2))

    assert result.stop_reason == "decisive"
    assert result.counts.voted == 48
    assert not any("Stopped after" in n.message for n in result.notices)
    assert any("2 of the 50" in n.message for n in result.notices)


@pytest.mark.anyio
async def test_an_undecided_run_buys_the_whole_panel(conn, aconn) -> None:
    """Counterbalanced orders under a position-only voter split near even, and an
    even split at n=50 proves nothing — so every chunk is bought and no stopped
    notice appears."""
    seed_japanese(conn, 50)

    result = await _run(aconn, size=50)

    assert result.stop_reason is None
    assert result.counts.voted == 50
    assert not any("Stopped after" in n.message for n in result.notices)


@pytest.mark.anyio
async def test_coverage_travels_as_data(conn, aconn) -> None:
    """The ticket's sharpest case: a target that named nowhere and one that named
    somewhere unservable resolve to the identical country tuple, and only `coverage`
    tells a reader which panel they are looking at."""
    seed_japanese(conn, 5)

    served = await _run(aconn, request=_ANYONE)
    substituted = await _run(aconn, request=_NOWHERE)

    assert served.selection.query.countries == substituted.selection.query.countries
    assert served.selection.query.coverage == "requested"
    assert substituted.selection.query.coverage == "unmatched"


@pytest.mark.anyio
async def test_an_empty_panel_is_refused_before_any_vote_is_paid_for(
    conn, aconn
) -> None:
    persist_pool(conn, [make_persona(id_="US-00000", country="US")])
    llm = SpyLLM()

    with pytest.raises(EmptyPanel):
        await _run(aconn, llm=llm)

    assert llm.calls == 0


@pytest.mark.anyio
async def test_a_panel_with_no_votes_is_refused_with_types_not_messages(
    conn, aconn
) -> None:
    seed_japanese(conn, 3)

    with pytest.raises(NoVotes) as excinfo:
        await _run(aconn, llm=FailingLLM())

    assert "RuntimeError" in str(excinfo.value)
    assert "entire output" not in str(excinfo.value)


@pytest.mark.anyio
async def test_usage_is_logged_even_when_no_verdict_comes_out(
    conn, aconn, caplog
) -> None:
    """The refusal path still paid for its failures' retries and for nothing else —
    but the log line must exist either way, because a run whose cost is unrecoverable
    is the thing this instrumentation exists to prevent."""
    seed_japanese(conn, 3)

    with (
        caplog.at_level(logging.INFO, logger="app.pipeline"),
        pytest.raises(NoVotes),
    ):
        await _run(aconn, llm=FailingLLM())

    (record,) = [r for r in caplog.records if r.message == "panel usage"]
    # 047/#145: the totals are fields a log query can filter on, not a repr
    # interpolated into the text — and the wall time sits beside them.
    assert record.votes == 0
    assert record.input_tokens == 0
    assert record.usage_reported == 0
    assert record.wall_seconds >= 0


@pytest.mark.anyio
async def test_the_run_records_its_own_wall_time(conn, aconn, caplog) -> None:
    """The one figure no per-vote number can give. Votes fan out concurrently,
    so their seconds do not add up to the run's; and only the wall clock says
    whether a slow run was one straggler holding its wave or every vote being
    slow at once. Without it a "why was that slow" question has no evidence
    but guesswork."""
    seed_japanese(conn, 3)

    with caplog.at_level(logging.INFO, logger="app.pipeline"):
        result = await _run(aconn)

    (record,) = [r for r in caplog.records if r.message == "panel usage"]
    assert record.wall_seconds >= record.seconds_slowest
    # The ledger's id, as a field beside the totals (047/#145).
    assert record.test_id == result.test_id


class TestEnactedContextAndTheVoteCache:
    """Two panels told to be different people are asking different questions, so
    they must not share cached answers — and a demographics-only run must still
    reach the votes it stored before this feature existed."""

    async def _votes(self, aconn, *, enacted: str = "", llm=None):
        panel = (
            await select_panel(
                aconn,
                "Japanese homeowners",
                size=3,
                translator=StubTranslator(JAPAN_REQUEST),
            )
        ).panel
        assert len(panel) == 3
        return await run_vote_loop(
            aconn,
            panel,
            variants=_VARIANTS,
            llm=llm or SpyLLM(),
            enacted=enacted,
            owner="acct-a",
        )

    @pytest.mark.anyio
    async def test_a_different_instruction_is_a_different_question(
        self, conn, aconn
    ) -> None:
        seed_japanese(conn, 5)
        await self._votes(aconn, enacted="You are a parent of young children.")

        spy = SpyLLM()
        await self._votes(
            aconn, enacted="You are a keen long-distance runner.", llm=spy
        )

        assert spy.calls == 3

    @pytest.mark.anyio
    async def test_the_same_instruction_replays_free(self, conn, aconn) -> None:
        seed_japanese(conn, 5)
        await self._votes(aconn, enacted="You are a parent of young children.")

        spy = SpyLLM()
        await self._votes(aconn, enacted="You are a parent of young children.", llm=spy)

        assert spy.calls == 0

    @pytest.mark.anyio
    async def test_an_enacted_run_never_serves_a_demographics_only_vote(
        self, conn, aconn
    ) -> None:
        """The bug this whole arrangement exists to prevent: without the context
        in the key, a panel told to be parents would be handed the answers of a
        panel that was told nothing."""
        seed_japanese(conn, 5)
        await self._votes(aconn)

        spy = SpyLLM()
        await self._votes(aconn, enacted="You are a parent of young children.", llm=spy)

        assert spy.calls == 3


class TestVoteCache:
    """Every vote is stored keyed on the fingerprint of the question asked,
    and the ledger is read before the model is — a re-run replays, a broken run
    resumes, and nothing downstream can tell a cached vote from a paid one."""

    @pytest.mark.anyio
    async def test_a_re_run_replays_the_whole_test_without_paying(
        self, conn, aconn
    ) -> None:
        seed_japanese(conn, 5)
        first = await _run(aconn)

        spy = SpyLLM()
        second = await _run(aconn, llm=spy)

        assert spy.calls == 0
        # Record equality includes test_id: a cached vote keeps the id of the run
        # that paid for it — provenance, not this run's correlation id.
        assert second.votes.records == first.votes.records
        assert second.verdict == first.verdict

    @pytest.mark.anyio
    async def test_a_resumed_run_pays_only_for_the_votes_that_failed(
        self, conn, aconn
    ) -> None:
        seed_japanese(conn, 5)
        first = await _run(aconn, llm=FlakyLLM(failures=2))
        assert len(first.votes.records) == 3

        spy = SpyLLM()
        second = await _run(aconn, llm=spy)

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

    @pytest.mark.anyio
    async def test_a_changed_headline_is_a_new_question(self, conn, aconn) -> None:
        seed_japanese(conn, 5)
        await _run(aconn)

        spy = SpyLLM()
        await run_panel_test(
            aconn,
            description="Japanese homeowners",
            variants=_VARIANTS | {"b": "A different promise"},
            size=5,
            translator=StubTranslator(),
            llm=spy,
        )

        assert spy.calls == 5

    @pytest.mark.anyio
    async def test_paid_votes_survive_the_run_dying_before_the_response(
        self, conn, aconn
    ) -> None:
        """The ledger's whole point: a run that dies at vote 180 must not cost 180
        votes to get back. The request connection only commits at a clean exit, so
        a store that waits for it dies with the run — votes must be committed per
        chunk, and a rollback (what a crashed request leaves behind) must not
        take them."""
        seed_japanese(conn, 5)
        await _run(aconn)
        # Roll back the connection that did the writing. Rolling back `conn` —
        # a different session — left the votes sitting in `aconn`'s own open
        # transaction, where the second run read its own uncommitted rows and
        # the assertion held whether or not the commit existed. Verified by
        # deleting the commit in `_chunk_votes` and watching this go red.
        await aconn.rollback()

        spy = SpyLLM()
        await _run(aconn, llm=spy)

        assert spy.calls == 0

    async def _loop(self, aconn, *, owner, llm=None):
        panel = (
            await select_panel(
                aconn,
                "Japanese homeowners",
                size=5,
                translator=StubTranslator(JAPAN_REQUEST),
            )
        ).panel
        return await run_vote_loop(
            aconn, panel, variants=_VARIANTS, llm=llm or SpyLLM(), owner=owner
        )

    @pytest.mark.anyio
    async def test_the_cache_is_scoped_to_the_owner(self, conn, aconn) -> None:
        """086/#177: a re-run replays free *for the account that paid*. Another
        account asking the byte-identical question is asking it for the first
        time — it pays, and it is never handed rows that quote someone else's
        submitted headlines."""
        seed_japanese(conn, 5)
        await self._loop(aconn, owner="acct-a")

        again = SpyLLM()
        await self._loop(aconn, owner="acct-a", llm=again)
        stranger = SpyLLM()
        await self._loop(aconn, owner="acct-b", llm=stranger)

        assert again.calls == 0
        assert stranger.calls == 5

    @pytest.mark.anyio
    async def test_an_ownerless_run_never_touches_the_ledger(self, conn, aconn) -> None:
        """`owner=None` is the demo's mode (086/#177): a replay spends nothing,
        so it has nothing to resume — it must not leave anonymous rows behind,
        and it must not read anyone's. Distinct from '', which is refused: None
        is a decision, '' is an accident."""
        seed_japanese(conn, 5)
        first = SpyLLM()
        await self._loop(aconn, owner=None, llm=first)
        second = SpyLLM()
        await self._loop(aconn, owner=None, llm=second)

        assert first.calls == 5
        assert second.calls == 5
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM votes")
            assert cur.fetchone() == (0,)

    @pytest.mark.anyio
    async def test_a_mid_run_402_still_resumes_for_its_owner(self, conn, aconn) -> None:
        """086/#177's done-when, verbatim: the votes a 402 stranded are still
        their buyer's resume buffer — the owner re-buys only what has no row,
        and another account re-buys everything, because the stranded rows were
        never theirs to resume from."""
        seed_japanese(conn, 5)
        stranded = await self._loop(aconn, owner="acct-a", llm=OutOfCreditLLM(paid=2))
        assert len(stranded.votes.records) == 2

        resumed = SpyLLM()
        result = await self._loop(aconn, owner="acct-a", llm=resumed)
        stranger = SpyLLM()
        await self._loop(aconn, owner="acct-b", llm=stranger)

        assert resumed.calls == 3
        assert len(result.votes.records) == 5
        assert stranger.calls == 5


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

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        with self._lock:
            self.calls += 1
            if self.calls <= self._paid:
                return voted("option_1")
        raise OutOfCredit("OpenRouter credit exhausted (402)")


class TestOutOfCredit:
    """A mid-run 402 is terminal for the run but not for the test — the cache
    holds what was paid for, so the stop's message is 'top up and resume', and the
    endpoint's code says whose fault it is (the account's, not the server's)."""

    @pytest.mark.anyio
    async def test_credit_running_out_mid_run_stops_asking_and_names_the_remedy(
        self, conn, aconn
    ) -> None:
        # Seeded with 75 *distinct* ages, not seed_japanese (which wraps at 60):
        # the prompt omits the persona id, so age-twins render identical prompts,
        # fingerprint identically, and share cached votes across chunks — content
        # is identity, and this test needs 75 distinguishable panelists.
        persist_pool(
            conn,
            [
                make_persona(id_=f"JP-{i:05d}", country="JP", age=20 + i)
                for i in range(75)
            ],
        )
        llm = OutOfCreditLLM(paid=25)

        result = await _run(aconn, size=75, llm=llm)

        assert result.counts.voted == 25
        # Chunk 3 was never attempted: 25 paid + 25 refused, not 75.
        assert llm.calls == 50
        (notice,) = [n for n in result.notices if "credit" in n.message.lower()]
        assert notice.severity == "warning"
        assert "25" in notice.message and "75" in notice.message
        assert "top up" in notice.message and "re-run" in notice.message

    @pytest.mark.anyio
    async def test_the_saved_votes_actually_resume(self, conn, aconn) -> None:
        seed_japanese(conn, 50)
        await _run(aconn, size=50, llm=OutOfCreditLLM(paid=25))

        spy = SpyLLM()
        result = await _run(aconn, size=50, llm=spy)

        assert result.counts.voted == 50
        assert spy.calls == 25

    @pytest.mark.anyio
    async def test_no_votes_and_no_credit_raises_out_of_credit_not_no_votes(
        self, conn, aconn
    ) -> None:
        seed_japanese(conn, 5)

        with pytest.raises(OutOfCredit):
            await _run(aconn, llm=OutOfCreditLLM(paid=0))

    @pytest.mark.anyio
    async def test_a_partially_paid_chunk_keeps_its_votes_and_tells_one_story(
        self, conn, aconn
    ) -> None:
        """The credit can die mid-chunk: the paid votes in that chunk must survive,
        and the 402 refusals must not also be narrated as 'transient' vote failures
        — 'a re-run may recover them' and 'credit ran out' beside each other read
        as a contradiction, and the credit notice already names the real remedy."""
        persist_pool(
            conn,
            [
                make_persona(id_=f"JP-{i:05d}", country="JP", age=20 + i)
                for i in range(75)
            ],
        )
        llm = OutOfCreditLLM(paid=30)

        result = await _run(aconn, size=75, llm=llm)

        assert result.counts.voted == 30
        assert llm.calls == 50
        (credit,) = [n for n in result.notices if "credit" in n.message.lower()]
        assert "30" in credit.message
        assert not any("did not vote" in n.message for n in result.notices)


class BlockingLLM:
    """Blocks inside the vote call until released, so a cancel lands mid-chunk
    rather than whenever the scheduler happens to look."""

    configuration = "blocking"

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self._lock = threading.Lock()

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        with self._lock:
            self.calls += 1
        self.entered.set()
        self.release.wait(10)
        return voted("option_1", "blocked")


@pytest.mark.anyio
async def test_a_cancel_stops_the_loop_at_the_chunk_in_flight(conn, aconn) -> None:
    """What a cancel costs, and what it must not cost.

    The chunk already in flight is lost: `asyncio.to_thread` cannot be
    cancelled, so its votes are paid for and never stored. That is accepted —
    preserving them needs a connection the chunk owns, which spends the budget
    112/#242 has yet to measure.

    What must not happen is the loop buying *another* chunk, or leaving work
    running behind the request that owned it. `asyncio.shield` used to wrap each
    chunk to keep a cancel from throwing votes away; measured against uvicorn's
    own forced-shutdown call it preserved none, and left the chunk writing to a
    connection `get_conn` had already closed.

    Both halves are asserted, because the first half alone is close to vacuous:
    with the shield gone `_chunk_votes` is plainly awaited and never becomes a
    Task, so "no task detached" can only ever catch a reintroduced shield. It is
    kept as exactly that — a tripwire — and the call count is what shows the loop
    actually stopped.
    """
    seed_japanese(conn, 75)
    llm = BlockingLLM()
    panel = (
        await select_panel(
            aconn,
            "Japanese homeowners",
            size=75,
            translator=StubTranslator(JAPAN_REQUEST),
        )
    ).panel
    assert len(panel) > VOTE_CONCURRENCY, "the panel must span more than one chunk"

    known = asyncio.all_tasks()
    task = asyncio.create_task(
        run_vote_loop(aconn, panel, variants=_VARIANTS, llm=llm, owner="acct-a")
    )
    try:
        # Deadlined: `pytest-timeout` is not installed, so a chunk that never
        # gets a worker would otherwise hang CI with no failing test.
        deadline = time.monotonic() + 30
        while not llm.entered.is_set():
            assert time.monotonic() < deadline, "the first chunk never started"
            await asyncio.sleep(0.01)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Not keyed on a function name: anything left running that this test did
        # not start, and did not know about beforehand.
        detached = asyncio.all_tasks() - known - {asyncio.current_task()}
        assert detached == set(), detached
    finally:
        llm.release.set()

    # The chunk in flight finishes in its thread; nothing after it may be bought.
    deadline = time.monotonic() + 30
    while llm.calls < VOTE_CONCURRENCY and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.2)

    assert llm.calls == VOTE_CONCURRENCY, (
        f"the loop bought {llm.calls} votes past a cancel; one chunk is"
        f" {VOTE_CONCURRENCY}"
    )
