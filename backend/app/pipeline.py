"""One panel test, end to end: a target description and two headlines in, a verdict out.

Plain Python and no FastAPI, so the whole run is testable against a stub translator and a
stub model. The HTTP layer maps the two refusals below onto status codes; nothing here
knows what a status code is.
"""

import logging
from dataclasses import dataclass
from uuid import uuid4

import psycopg

from app.schemas import Notice, PanelCounts, PanelVerdict, VoteTally
from app.targeting import PanelSelection, TargetTranslator, select_panel
from app.verdict import StopReason, panel_verdict, stopping_decision, tally_votes
from app.vote import (
    VOTE_CONCURRENCY,
    PanelLLM,
    PanelVotes,
    collect_panel_votes,
    total_usage,
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


def _vote_shortfall_notice(votes: PanelVotes, matched: int) -> tuple[Notice, ...]:
    """Failed votes as a message, not an arithmetic exercise.

    Worded for its remedy, which is what separates it from retrieval's shortfall: the
    pool cannot give more matched personas, but a failed vote is transient — the
    panelist exists and a re-run may recover them (resume is 010e).
    """
    if not votes.failures:
        return ()
    return (
        Notice(
            severity="warning",
            message=(
                f"{len(votes.failures)} of the {matched} matched panelists did not "
                "vote, so the verdict rests on fewer votes. These failures are "
                "transient — a re-run may recover them."
            ),
        ),
    )


def run_panel_test(
    conn: psycopg.Connection,
    *,
    description: str,
    variants: dict[str, str],
    size: int,
    translator: TargetTranslator,
    llm: PanelLLM,
) -> PanelTestResult:
    """Vote in chunks, stop when the report would already make a call.

    The stopping bar is `credible_mass` itself — the run stops exactly when the
    render-time recommendation would fire, so there is no second threshold to
    source. A run that loses some votes reports the counts and offers the verdict;
    only a run with *no* votes has nothing to report (010b decided no partial-run
    rule beyond that).
    """
    selection = select_panel(conn, description, size=size, translator=translator)
    # Refused before the panel model is touched: nothing has been spent yet on a
    # target nobody matches, and nothing should be.
    if not selection.panel:
        raise EmptyPanel(f"no persona matches this target (size {size} requested)")

    # A correlation id only — votes are not persisted until 010e, so this ties the
    # records and the log lines of one run together and nothing more.
    test_id = str(uuid4())

    # Chunks are one concurrency-load each, so no worker idles mid-chunk and the
    # dev profile (size 25) degenerates to a single fan-out. A streak is broken by
    # any boundary that reads differently — including the direction of a decisive,
    # so a lead that flips sides cannot accumulate confirmations across the flip.
    votes = PanelVotes(records=[], usage=(), failures=())
    stop_reason: StopReason | None = None
    asked = 0
    streak = 0
    last_reading: tuple[StopReason, str] | None = None
    for start in range(0, len(selection.panel), VOTE_CONCURRENCY):
        chunk_panel = selection.panel[start : start + VOTE_CONCURRENCY]
        chunk = collect_panel_votes(
            test_id=test_id, variants=variants, panel=chunk_panel, llm=llm
        )
        asked += len(chunk_panel)
        votes = PanelVotes(
            records=votes.records + chunk.records,
            usage=votes.usage + chunk.usage,
            failures=votes.failures + chunk.failures,
        )
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

    # Before the no-votes check, so a fully refused run still records what it spent.
    logger.info("panel usage test_id=%s: %s", test_id, total_usage(votes.usage))

    if not votes.records:
        kinds = ", ".join(sorted({f.error.split(":")[0] for f in votes.failures}))
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
        + _stopped_early_notice(stop_reason, asked, len(selection.panel))
        + _vote_shortfall_notice(votes, len(selection.panel)),
        stop_reason=stop_reason,
    )
