"""One panel test, end to end: a target description and two headlines in, a verdict out.

Plain Python and no FastAPI, so the whole run is testable against a stub translator and a
stub model. The HTTP layer maps the two refusals below onto status codes; nothing here
knows what a status code is.
"""

import logging
from dataclasses import dataclass
from uuid import uuid4

import psycopg

from app.schemas import PanelCounts, PanelVerdict, VoteTally
from app.targeting import PanelSelection, TargetTranslator, select_panel
from app.verdict import panel_verdict, tally_votes
from app.vote import PanelLLM, PanelVotes, collect_panel_votes, total_usage

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
    """

    selection: PanelSelection
    votes: PanelVotes
    tally: VoteTally
    verdict: PanelVerdict
    counts: PanelCounts


def run_panel_test(
    conn: psycopg.Connection,
    *,
    description: str,
    variants: dict[str, str],
    size: int,
    translator: TargetTranslator,
    llm: PanelLLM,
) -> PanelTestResult:
    """One full panel, one posterior — no stopping loop (010d) and no partial-run
    rule (010b). A run that loses some votes reports the counts and offers the
    verdict; only a run with *no* votes has nothing to report.
    """
    selection = select_panel(conn, description, size=size, translator=translator)
    # Refused before the panel model is touched: nothing has been spent yet on a
    # target nobody matches, and nothing should be.
    if not selection.panel:
        raise EmptyPanel(f"no persona matches this target (size {size} requested)")

    # A correlation id only — votes are not persisted until 010e, so this ties the
    # records and the log lines of one run together and nothing more.
    test_id = str(uuid4())
    votes = collect_panel_votes(
        test_id=test_id, variants=variants, panel=selection.panel, llm=llm
    )
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
    )
