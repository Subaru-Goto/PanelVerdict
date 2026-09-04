"""One panel test, end to end: a target description and two headlines in, a verdict out.

Plain Python and no FastAPI, so the whole run is testable against a stub translator and a
stub model. The HTTP layer maps the two refusals below onto status codes; nothing here
knows what a status code is.
"""

import asyncio
import logging
from dataclasses import asdict, dataclass
from time import perf_counter
from uuid import uuid4

import psycopg

from app.persistence import load_votes, store_votes
from app.schemas import (
    Notice,
    PanelCounts,
    PanelVerdict,
    Persona,
    VoteRecord,
    VoteTally,
)
from app.targeting import PanelSelection, TargetTranslator, select_panel
from app.verdict import StopReason, panel_verdict, stopping_decision, tally_votes
from app.vote import (
    ORDER_SEED,
    VOTE_CONCURRENCY,
    OutOfCredit,
    PanelLLM,
    PanelVotes,
    VoteFailure,
    VoteUsage,
    build_vote_request,
    collect_panel_votes,
    presentation_orders,
    total_usage,
    vote_fingerprint,
)

logger = logging.getLogger(__name__)


class EmptyPanel(Exception):
    """No persona matched the target, so there is nobody to ask.

    Separate from `NoVotes` because the cause is the request, not the provider: the
    target named an audience this pool cannot serve at all. Nothing was spent.
    """


class NoVotes(Exception):
    """A panel was drawn and not one member returned a usable vote.

    Carries the failing exception *types* only. A failure message can contain provider
    response text and the model's own output, and this string reaches a caller.
    """


@dataclass(frozen=True)
class PanelTestResult:
    """Everything one run produced, with the panel it was drawn from still attached.

    `selection` travels whole rather than as the panel list alone, because the verdict is
    unreadable without the query and notices that produced it — a narrower panel than
    asked for and a panel that matched exactly are the same list of personas.

    `notices` is the complete set — the selection's plus anything the run itself added —
    for the same reason `PanelSelection.notices` already is: one place to look rather
    than two lists to remember to concatenate.
    """

    selection: PanelSelection
    votes: PanelVotes
    tally: VoteTally
    verdict: PanelVerdict
    counts: PanelCounts
    notices: tuple[Notice, ...]
    stop_reason: StopReason | None
    # What a stored report is keyed on (117/#252).
    test_id: str


# Two consecutive boundaries must agree before a mid-run stop. Sourced by
# simulation (docs/research/adaptive-stopping.md): at the 0.95 bar a single
# crossing calls a false decisive on 2.3% of genuinely tied panels against the
# single-look baseline's ~0.03%, while two crossings hold it to 0.4% — under the
# 1.2% this project accepted when it simulated the old label rule — and keep the
# savings (137 of 200 votes at a true 65/35).
_STOP_CONFIRMATIONS = 2


def _stopped_early_notice(
    reason: StopReason | None, asked: int, matched: int
) -> tuple[Notice, ...]:
    """A deliberate early stop is an answer, not a shortfall — severity `reading`.

    Guarded on panelists actually going *unasked*, not on the vote count: a stop
    firing on the last chunk with a few failed votes left nobody unasked, and
    claiming "the remaining votes would not have changed the call" about votes
    that merely failed would be false.
    """
    if reason is None or asked >= matched:
        return ()
    answer = {
        "decisive": "the panel had already decided",
        "practical_tie": "the difference was already credibly too small to matter",
    }[reason]
    return (
        Notice(
            severity="reading",
            message=(
                f"Stopped after {asked} of the {matched} matched panelists: "
                f"{answer}. The rest went unasked, so this is an answer, not a "
                "shortfall."
            ),
        ),
    )


def _failure_kind(failure: VoteFailure) -> str:
    """The exception type's name — the only part of a failure string safe to act
    on or forward, since the rest can carry provider and model text."""
    return failure.error.split(":")[0]


def _credit_notice(exhausted: bool, voted: int, matched: int) -> tuple[Notice, ...]:
    """The 402 stop's message names its remedy, like every notice here: the votes
    already cast are in the ledger, so the run is suspended, not lost."""
    if not exhausted:
        return ()
    return (
        Notice(
            severity="warning",
            message=(
                f"OpenRouter credit ran out after {voted} of the {matched} matched "
                "panelists voted. Rejected requests are not charged, and the votes "
                "already cast are saved — top up and re-run to resume where this "
                "stopped."
            ),
        ),
    )


def _vote_shortfall_notice(votes: PanelVotes, matched: int) -> tuple[Notice, ...]:
    """Failed votes as a message, not an arithmetic exercise.

    Worded for its remedy, which is what separates it from retrieval's shortfall: the
    pool cannot give more matched personas, but a failed vote is transient — the
    panelist exists and a re-run may recover them (a resume serves it from the ledger).

    Credit refusals are excluded: their story belongs to the credit notice, and
    "transient — a re-run may recover them" beside "credit ran out" would read as a
    contradiction about the same failures.
    """
    # NotCaptured is the demo's replay of a vote the captured run itself lost
    # (061/#156): permanent by construction, so promising a re-run will
    # recover it would be invented copy on the page arguing the report is real.
    replayed = [f for f in votes.failures if _failure_kind(f) == "NotCaptured"]
    transient = [
        f
        for f in votes.failures
        if _failure_kind(f) not in ("OutOfCredit", "NotCaptured")
    ]
    notices = []
    if replayed:
        notices.append(
            Notice(
                severity="warning",
                message=(
                    f"{len(replayed)} of the {matched} matched panelists cast "
                    "no vote when this demo was captured, so the verdict "
                    "rests on fewer votes — the replay reports the run as it "
                    "was bought."
                ),
            )
        )
    if transient:
        notices.append(
            Notice(
                severity="warning",
                message=(
                    f"{len(transient)} of the {matched} matched panelists did "
                    "not vote, so the verdict rests on fewer votes. These "
                    "failures are transient — a re-run may recover them."
                ),
            )
        )
    return tuple(notices)


async def _chunk_votes(
    conn: psycopg.AsyncConnection,
    panel: list[Persona],
    *,
    test_id: str,
    variants: dict[str, str],
    llm: PanelLLM,
    # No default on the private hops. A forgotten argument on a chain this long
    # degrades silently to a demographics-only run — the panel is told nothing and
    # nothing raises — so the ones nobody outside this module calls fail loudly
    # instead. The public seams keep their default, because most runs have none.
    enacted: str,
    owner: str | None,
) -> PanelVotes:
    """One chunk's votes: the ledger first, the model only for what is missing.

    Orders are fixed for the whole chunk *before* the hit/miss split — a fresh draw
    over the misses alone would re-pair panelists with positions, and every
    would-be hit on the next run would fingerprint as a new question.

    Cached and fresh votes merge back in panel order, the records' documented
    ordering, with a None usage entry per cached vote so usage stays parallel to
    records. A cached vote costs nothing today, and None — "nothing reported" — is
    exactly what the usage totals should say about it.
    """
    first_id, second_id = variants
    orders = presentation_orders((first_id, second_id), len(panel), seed=ORDER_SEED)
    fingerprints = {
        persona.id: vote_fingerprint(
            build_vote_request(persona, order, variants=variants, enacted=enacted),
            configuration=llm.configuration,
        )
        for persona, order in zip(panel, orders)
    }
    # `owner=None` skips the ledger both ways (086/#177): the demo replays a
    # captured run at $0, so it has nothing to resume, must leave no anonymous
    # rows behind, and must never read an account's. An owned run reads only
    # within its owner — the WHERE clause is the privacy boundary.
    cached = (
        {}
        if owner is None
        else await load_votes(conn, list(fingerprints.values()), owner=owner)
    )
    # The read is over, so close its transaction before the wave: minutes of
    # model calls with the connection idle-in-transaction is the state
    # `idle_in_transaction_session_timeout` and pooler reapers kill — and a
    # session killed mid-wave means the thread returns paid votes that
    # `store_votes` has no connection to record: the loss the ledger exists to
    # prevent. Also the ACCESS SHARE a concurrent deploy's DDL queued behind.
    # A commit, and a safe one: everything that writes on this connection
    # before the wave commits itself (`_charge_ledger`), so what is pending
    # here is reads. The ledger's own ordering below — store, then commit —
    # is untouched (113/#243).
    await conn.commit()
    misses = [
        (persona, order)
        for persona, order in zip(panel, orders)
        if fingerprints[persona.id] not in cached
    ]
    # 042/#140's `ThreadPoolExecutor` is untouched, and must not run here: a
    # panel is minutes of model calls, and awaiting them on the event loop
    # would stall every other request in the process for the whole run.
    fresh = await asyncio.to_thread(
        collect_panel_votes,
        test_id=test_id,
        variants=variants,
        panel=[persona for persona, _ in misses],
        llm=llm,
        enacted=enacted,
        orders=[order for _, order in misses],
    )
    if owner is not None:
        await store_votes(
            conn,
            {fingerprints[record.persona_id]: record for record in fresh.records},
            owner=owner,
        )
    # Committed per chunk, not per request: the endpoint's connection only commits
    # at a clean exit, so a store that waited for it would die with the run — and
    # the ledger exists precisely so a run that dies at vote 180 does not cost 180
    # votes to get back.
    await conn.commit()

    fresh_pairs = {
        record.persona_id: (record, usage)
        for record, usage in zip(fresh.records, fresh.usage)
    }
    records: list[VoteRecord] = []
    usage: list[VoteUsage | None] = []
    for persona in panel:
        if (hit := cached.get(fingerprints[persona.id])) is not None:
            records.append(hit)
            usage.append(None)
        elif (pair := fresh_pairs.get(persona.id)) is not None:
            records.append(pair[0])
            usage.append(pair[1])
    return PanelVotes(records=records, usage=tuple(usage), failures=fresh.failures)


@dataclass(frozen=True)
class CollectedVotes:
    """What the vote loop bought. `assemble_result` turns it into a verdict."""

    votes: PanelVotes
    asked: int
    stop_reason: StopReason | None
    credit_exhausted: bool
    # The id this run stamped on the votes it paid for, carried out so the
    # stored report can be keyed on it (117/#252) — a report and the votes that
    # run bought are then joinable. Not readable off the votes themselves: a
    # cached vote keeps the id of the run that paid for it.
    test_id: str


async def run_vote_loop(
    conn: psycopg.AsyncConnection,
    panel: list[Persona],
    *,
    variants: dict[str, str],
    llm: PanelLLM,
    enacted: str = "",
    test_id: str | None = None,
    owner: str | None,
) -> CollectedVotes:
    """Vote in chunks, stop when the report would already make a call.

    The stopping bar is `credible_mass` itself — the run stops exactly when the
    render-time recommendation would fire, so there is no second threshold to
    source.

    Lifted out of `run_panel_test` unchanged: byte-identical replay (010e) is
    what makes a re-run free, and the $0 demo depends on it.
    """
    # Stamped on the votes this run pays for. A cached vote keeps the test_id of
    # the run that paid for it — the ledger records provenance, and identity across
    # runs is the fingerprint's job, not this id's. The graph passes its thread
    # id, so the waiting screen can count this run's rows by an id the client
    # already holds (021/#126); a caller with no thread gets a minted one.
    test_id = test_id or str(uuid4())
    started = perf_counter()

    # Chunks are one concurrency-load each, so no worker idles mid-chunk and the
    # dev profile (size 25) degenerates to a single fan-out — one boundary, so
    # the stop can never fire there (042/#140, pinned). A streak is broken by
    # any boundary that reads differently — including the direction of a decisive,
    # so a lead that flips sides cannot accumulate confirmations across the flip.
    votes = PanelVotes(records=[], usage=(), failures=())
    stop_reason: StopReason | None = None
    credit_exhausted = False
    asked = 0
    streak = 0
    last_reading: tuple[StopReason, str] | None = None
    for start in range(0, len(panel), VOTE_CONCURRENCY):
        chunk_panel = panel[start : start + VOTE_CONCURRENCY]
        # Plainly awaited, and a shield here was tried and measured. The worry
        # was real — `asyncio.to_thread` cannot be cancelled, so a cancel landing
        # mid-chunk leaves the worker finishing all 25 paid model calls while
        # `store_votes` and the commit below never run, and the resumed run
        # re-buys what it just paid for. `asyncio.shield` does not address it:
        # cancelling the awaiter is exactly what a shield permits, so the handler
        # unwinds, `get_conn` closes this connection, and the detached chunk then
        # reaches a closed one. Measured against uvicorn's own forced-shutdown
        # call, shielded and plain preserved the same votes — the shield's only
        # effect was an extra `OperationalError` and a chunk outliving its
        # request. Measured in
        # `docs/research/async-cancellation-and-connections.md`, which also
        # records that nothing cancels this handler in the deployment today.
        # Preserving the in-flight chunk needs a connection the chunk owns, which
        # spends the connection budget 112/#242 has yet to measure.
        chunk = await _chunk_votes(
            conn,
            chunk_panel,
            test_id=test_id,
            variants=variants,
            llm=llm,
            enacted=enacted,
            owner=owner,
        )
        asked += len(chunk_panel)
        votes = PanelVotes(
            records=votes.records + chunk.records,
            usage=votes.usage + chunk.usage,
            failures=votes.failures + chunk.failures,
        )
        # A 402 is terminal for the run: every later chunk would fail the same way,
        # so fanning them out buys latency and nothing else. The failure type name
        # is the signal, the same channel NoVotes reads.
        if any(_failure_kind(f) == "OutOfCredit" for f in chunk.failures):
            credit_exhausted = True
            break
        if not votes.records:
            continue
        tally = tally_votes(votes.records, variant_ids=list(variants))
        reason = stopping_decision(preferring_b=tally.counts["b"], total=tally.total)
        if reason is None:
            streak, last_reading = 0, None
            continue
        leader = max(tally.counts, key=lambda vid: tally.counts[vid])
        reading = (reason, leader if reason == "decisive" else "")
        streak = streak + 1 if reading == last_reading else 1
        last_reading = reading
        if streak >= _STOP_CONFIRMATIONS:
            stop_reason = reason
            break

    # Before the refusal checks, so a fully refused run still records what it spent.
    #
    # Wall time is logged beside the per-vote figures because neither can be
    # derived from the other: votes fan out, so their seconds do not add to the
    # run's, and only the two together say whether a slow run was one straggler
    # holding its wave or every vote being slow at once.
    logger.info(
        "panel usage",
        extra={
            "test_id": test_id,
            "wall_seconds": round(perf_counter() - started, 3),
            **asdict(total_usage(votes.usage)),
        },
    )
    return CollectedVotes(
        votes=votes,
        asked=asked,
        stop_reason=stop_reason,
        credit_exhausted=credit_exhausted,
        test_id=test_id,
    )


def _enacted_notice(enacted: str) -> tuple[Notice, ...]:
    """What the report owes a reader when part of the panel was told who to be.

    The demographics behind a verdict are surveyed — real people answered a real
    survey, and the pool is drawn from their answers. This part of the portrayal
    is not: it is a model acting a sentence a customer wrote. Both are in the same
    verdict, and a report that does not separate them is claiming evidence it does
    not have (094/#200).

    The sentence itself is quoted, because a caveat that says "some instruction
    was given" leaves the reader guessing which part of the panel to discount.
    """
    if not enacted:
        return ()
    return (
        Notice(
            # `reading`, not `warning`: the panel *is* the one asked for. What
            # this says is the interpretation the verdict rests on, which is the
            # distinction that severity exists to draw.
            severity="reading",
            message=(
                "Every panelist was instructed: "
                f"\u201c{enacted}\u201d — instructed, not sampled. Their age, "
                "gender, education and income come from survey data; this part of "
                "the portrayal is the model's."
            ),
        ),
    )


def assemble_result(
    selection: PanelSelection,
    collected: CollectedVotes,
    *,
    variants: dict[str, str],
    size: int,
    enacted: str = "",
) -> PanelTestResult:
    """Read what was bought as a verdict, or refuse to.

    A run that loses some votes reports the counts and offers the verdict; only
    a run with *no* votes has nothing to report, and there is no partial-run
    rule beyond that.
    """
    votes = collected.votes
    if collected.credit_exhausted and not votes.records:
        raise OutOfCredit(
            "OpenRouter credit is exhausted and no vote was cast — rejected "
            "requests are not charged. Top up and re-run: votes from earlier runs "
            "are saved and resume free."
        )
    if not votes.records:
        kinds = ", ".join(sorted({_failure_kind(f) for f in votes.failures}))
        raise NoVotes(f"0 of {len(selection.panel)} panelists voted ({kinds})")

    tally = tally_votes(votes.records, variant_ids=list(variants))
    return PanelTestResult(
        selection=selection,
        votes=votes,
        tally=tally,
        verdict=panel_verdict(preferring_b=tally.counts["b"], total=tally.total),
        counts=PanelCounts(
            requested=size,
            matched=len(selection.panel),
            voted=len(votes.records),
        ),
        notices=selection.notices
        + _enacted_notice(enacted)
        + _stopped_early_notice(
            collected.stop_reason, collected.asked, len(selection.panel)
        )
        + _credit_notice(
            collected.credit_exhausted, len(votes.records), len(selection.panel)
        )
        + _vote_shortfall_notice(votes, len(selection.panel)),
        stop_reason=collected.stop_reason,
        test_id=collected.test_id,
    )


# The one ungated caller's identity in the vote ledger (086/#177): experiment
# scripts have no account, but their re-runs still resume each other. The
# prefix keeps it out of the namespace real identities live in — subjects are
# UUIDs and the pre-auth fallback is address-shaped, but a ledger row should
# never be one unset config away from being mistaken for a customer's.
EXPERIMENT_OWNER = "internal:experiment"


async def run_panel_test(
    conn: psycopg.AsyncConnection,
    *,
    description: str,
    variants: dict[str, str],
    size: int,
    translator: TargetTranslator,
    llm: PanelLLM,
) -> PanelTestResult:
    """Select a panel, buy its votes, read the verdict — the whole run, ungated.

    The experiment pipeline only: the product's graph settles its reading from
    the controls and never translates (094), so this is the one caller the
    translator has left.
    """
    selection = await select_panel(conn, description, size=size, translator=translator)
    # Refused before the panel model is touched: nothing has been spent yet on a
    # target nobody matches, and nothing should be.
    if not selection.panel:
        raise EmptyPanel(f"no persona matches this target (size {size} requested)")
    # A fixed label, not an account: this seam has no caller with an identity,
    # and experiment re-runs must keep replaying each other for free — scoped
    # under one shared owner rather than the pre-086 everyone (086/#177).
    collected = await run_vote_loop(
        conn, selection.panel, variants=variants, llm=llm, owner=EXPERIMENT_OWNER
    )
    return assemble_result(selection, collected, variants=variants, size=size)
