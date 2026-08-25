"""The evaluate run as a LangGraph graph, with a human gate before it spends.

    START -> screen -> select -> confirm --(accept)--> vote -> assemble -> END
                         ^         |
                         +-(adjust)+          interrupt() at confirm

The rule this enforces: **no panel is voted on whose reading a human has not
accepted.**

- `confirm` pauses with `interrupt()`. Pausing buys nothing.
- The pause is checkpointed, so it survives a restart or a deploy.
- The vote loop is one node, unchanged from the pipeline. Its byte-identical
  replay is what makes a re-run free (010e), so it was moved, never edited.

Dependencies (connection, model client, screener) are closed over rather than
put in state, because state is serialized to Postgres at every step. The graph
is built per request, which is also how a resume can land on a different worker
than the start did.

Tickets: 076/#166 (this graph), 067 (why hand-authored), 077/#167 (the gate's
interface).
"""

from typing import Literal, TypedDict

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from app.analyst import PanelComposition, composition_of
from app.config import USD_PER_VOTE
from app.persistence import retrieve_panel
from app.pipeline import (
    CollectedVotes,
    EmptyPanel,
    PanelTestResult,
    assemble_result,
    buy_panel_votes,
)
from app.schemas import Notice, Persona, TargetQuery
from app.screening import Screener, screen_inputs
from app.targeting import PANEL_SEED, PanelSelection, TargetTranslator, select_panel
from app.vote import PanelLLM


class PanelPreview(BaseModel):
    """What the reader sees while the run holds, before anything is bought.

    Every field is already computed when the pause happens, so asking costs
    nothing.
    """

    query: TargetQuery
    matched: int
    # None only when nobody matched.
    composition: PanelComposition | None
    notices: list[Notice]
    # size x USD_PER_VOTE. Accuracy is 070/#161's job.
    estimated_usd: float


class GateDecision(BaseModel):
    """How a human answers the gate: accept, or adjust the reading.

    - `accept` buys the votes.
    - `adjust` carries an edited reading and re-seats the panel. Free and
      deterministic: pure SQL, never a second translation call.

    There is no `redraw`. It was cut in 077 because filtering happens before
    sampling, so it could never change who matched.
    """

    action: Literal["accept", "adjust"]
    query: TargetQuery | None = None


class EvaluateState(TypedDict, total=False):
    """Everything that survives a restart. Serializable by construction.

    `panel` holds the personas themselves, not their ids: re-reading them on
    resume could return different people than the human approved.
    """

    description: str
    variants: dict[str, str]
    size: int
    # Set by the caller when this reading was already approved, so a repeat run
    # is not stopped again. The graph never sets it.
    reading_accepted: bool
    query: TargetQuery | None
    panel: list[Persona]
    notices: list[Notice]
    decision: Literal["accept", "adjust"] | None
    # What a human edited the reading to. Kept apart from `query` so `select`
    # can tell whether the reading actually changed.
    edited: TargetQuery | None
    collected: CollectedVotes | None
    result: PanelTestResult | None


def _preview(state: EvaluateState) -> PanelPreview:
    panel = state["panel"]
    return PanelPreview(
        query=state["query"],
        matched=len(panel),
        composition=composition_of(panel),
        notices=state.get("notices", []),
        # Priced at what the run may buy, matching the ledger's charge.
        estimated_usd=len(panel) * USD_PER_VOTE,
    )


def build_evaluate_graph(
    *,
    conn: psycopg.Connection,
    translator: TargetTranslator,
    llm: PanelLLM,
    screener: Screener | None,
    checkpointer: BaseCheckpointSaver,
):
    """Compile the evaluate graph with this request's dependencies bound.

    START -> screen -> select -> confirm --(accept)--> vote -> assemble -> END
                         ^         |
                         +-(adjust)+          interrupt() at confirm
    """

    def screen(state: EvaluateState) -> EvaluateState:
        """Screen the customer's text before anything else runs."""
        screen_inputs(screener, [state["description"], *state["variants"].values()])
        return {}

    def select(state: EvaluateState) -> EvaluateState:
        """Draw the panel. Translates once per run, then re-selects with SQL."""
        # Translate only on the first pass. A second translation would be paid
        # and could disagree with the edit it was asked to apply.
        settled = state.get("query")
        if settled is None:
            selection = select_panel(
                conn,
                state["description"],
                size=state["size"],
                translator=translator,
            )
            notices = list(selection.notices)
        else:
            target = state.get("edited") or settled
            selection = PanelSelection(
                panel=retrieve_panel(conn, target, size=state["size"], seed=PANEL_SEED),
                query=target,
                notices=(),
            )
            # Notices explain how the customer's words were read, so they are
            # kept when the reading is unchanged and dropped when it is edited.
            notices = list(state.get("notices", [])) if target == settled else []
        if not selection.panel and settled is None:
            # Nothing to show and nothing to approve: the run never starts.
            raise EmptyPanel(
                f"no persona matches this target (size {state['size']} requested)"
            )
        if not selection.panel:
            # An *edit* that matches nobody must not raise. The edit is already
            # in state, so every resume would fail here and the run would be
            # unrecoverable. Go back to the gate reading zero instead.
            return {
                "query": selection.query,
                "panel": [],
                "notices": [
                    Notice(
                        severity="warning",
                        message=(
                            "Nobody in the pool matches that reading. Widen it "
                            "and look again — nothing has been spent."
                        ),
                    )
                ],
            }
        return {
            "query": selection.query,
            "panel": selection.panel,
            "notices": notices,
        }

    def confirm(state: EvaluateState) -> EvaluateState:
        """Hold, and show the reader what their money would buy.

        Keep everything above `interrupt()` cheap: LangGraph re-runs a node from
        the top on resume, so expensive work here would be paid for twice.
        """
        if state.get("reading_accepted"):
            return {"decision": "accept"}
        decision = GateDecision.model_validate(
            interrupt(_preview(state).model_dump(mode="json"))
        )
        if decision.action == "adjust":
            # `select` picks this up and re-seats without translating.
            return {"decision": "adjust", "edited": decision.query or state["query"]}
        return {"decision": "accept"}

    def vote(state: EvaluateState) -> EvaluateState:
        """The one paid node. Unchanged from the pipeline."""
        return {
            "collected": buy_panel_votes(
                conn, state["panel"], variants=state["variants"], llm=llm
            )
        }

    def assemble(state: EvaluateState) -> EvaluateState:
        selection = PanelSelection(
            panel=state["panel"],
            query=state["query"],
            notices=tuple(state.get("notices", [])),
        )
        return {
            "result": assemble_result(
                selection,
                state["collected"],
                variants=state["variants"],
                size=state["size"],
            )
        }

    def after_confirm(state: EvaluateState) -> Literal["select", "vote"]:
        """Route to `vote` only for an accepted, non-empty panel.

        An accept with nobody seated has nobody to ask, so it returns to the
        gate. The interface will not offer it; this does not rely on that.
        """
        if state.get("decision") == "adjust" or not state["panel"]:
            return "select"
        return "vote"

    builder = StateGraph(EvaluateState)
    builder.add_node("screen", screen)
    builder.add_node("select", select)
    builder.add_node("confirm", confirm)
    builder.add_node("vote", vote)
    builder.add_node("assemble", assemble)
    builder.add_edge(START, "screen")
    builder.add_edge("screen", "select")
    builder.add_edge("select", "confirm")
    builder.add_conditional_edges("confirm", after_confirm)
    builder.add_edge("vote", "assemble")
    builder.add_edge("assemble", END)
    return builder.compile(checkpointer=checkpointer)
