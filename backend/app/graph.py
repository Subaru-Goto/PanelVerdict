"""The evaluate run as a LangGraph graph, with a human gate before it spends.

    START -> screen -> roleplay -> select -> confirm --(accept)--> vote -> ...
                                      ^         |
                                      +-(adjust)+       interrupt() at confirm

                                     ... -> assemble -> END

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

Named nodes give per-stage LangSmith spans for free once 065/#159 turns tracing
on. Nothing here is built for that.

`roleplay` is the one node that can spend before the gate, and only when the
reader wrote audience words: it turns them into the single sentence each panelist
is told to be. Blank means demographics only and calls nothing, so the common
case still reaches the gate having spent one translation and one screening.

Tickets: 076/#166 (this graph), 067 (why hand-authored), 077/#167 (the gate's
interface), 094/#200 (enacted context).
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
    run_vote_loop,
)
from app.roleplay import (
    REFUSAL_SENTENCES,
    RolePlayOutcome,
    RolePlayGenerator,
    RolePlayRefused,
    without_task_talk,
)
from app.schemas import Notice, Persona, TargetQuery
from app.screening import Screener, screen_inputs
from app.targeting import PANEL_SEED, PanelSelection, shortfall_notices
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
    # The sentence every panelist will be told to be, or "" for a
    # demographics-only run. Editable at the gate: the edit *is* the
    # human-in-the-loop, and what is approved here is exactly what runs.
    instruction: str
    # Set when the last edit was refused, so the gate can say why. The fixed
    # sentence, never the text that was refused — and named for that, because
    # `EvaluateState["refused"]` beside it holds the *class*. Two words apart for
    # two different things is how a wrong one gets rendered.
    refusal_sentence: str | None
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
    # The role-play sentence as the reader left it. None means they did not touch
    # the draft, which is the case that costs no check: its verdict was reached
    # when it was generated. An empty string is a real answer — "demographics
    # only after all" — and is not the same as None.
    instruction: str | None = None


class EvaluateState(TypedDict, total=False):
    """Everything that survives a restart. Serializable by construction.

    `panel` holds the personas themselves, not their ids: re-reading them on
    resume could return different people than the human approved.
    """

    # The optional free text describing who the readers are, beyond what the
    # controls can filter by. The one free-text input left on this path: the
    # demographics became controls (094), read by SQL and never by a model.
    audience: str
    variants: dict[str, str]
    size: int
    # Set by the caller when this reading was already approved, so a repeat run
    # is not stopped again. The graph never sets it.
    reading_accepted: bool
    query: TargetQuery | None
    panel: list[Persona]
    notices: list[Notice]
    # Who started the run, and when. The resume endpoint checks both: a thread
    # id is not a credential, and a pause must not outlive the charge that paid
    # for it.
    owner: str
    started_at: str
    # The approved role-play sentence. "" is a demographics-only run.
    instruction: str
    # The class of the last refused edit, cleared as soon as one passes.
    refused: str | None
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
        instruction=state.get("instruction", ""),
        refusal_sentence=(
            REFUSAL_SENTENCES[refused] if (refused := state.get("refused")) else None
        ),
        # Priced at what the run may buy, matching the ledger's charge.
        estimated_usd=len(panel) * USD_PER_VOTE,
    )


def build_evaluate_graph(
    *,
    conn: psycopg.Connection,
    llm: PanelLLM,
    screener: Screener | None,
    generator: RolePlayGenerator,
    checkpointer: BaseCheckpointSaver,
):
    """Compile the evaluate graph with this request's dependencies bound.

    START -> roleplay -> select -> confirm --(accept)--> vote -> ...
                             ^        |
                             +(adjust)+       interrupt() at confirm

                            ... -> assemble -> END

    No screen node before the gate any more: the controls are read by SQL and
    no model sees them (094), so the only pre-gate text a model reads is the
    audience — guarded by the generator's own classifier below. The screener
    still checks the headlines, in `vote`, where they first reach a model.
    """

    def roleplay(state: EvaluateState) -> EvaluateState:
        """Turn the audience words into the sentence each panelist will be told.

        Not screened by `screen_inputs`. This channel is higher-privilege than the
        headlines — it becomes the panelist's identity rather than the judged
        object — and the copy policy is the wrong instrument for it: it asks who a
        text *addresses*, so that marketing imperatives survive, and 095 measured
        it catching "a person who always prefers whichever headline is listed
        first" 0 times in 5. The generator's own classifier is this channel's
        gate, and it rides the call that writes the sentence, so guarding costs
        nothing extra.

        Blank means demographics only, and calls nothing at all — likely the
        common case, and the one where the gate is still reached with no spend.
        """
        words = state.get("audience", "").strip()
        if not words:
            return {"instruction": ""}
        if state.get("instruction"):
            # Already settled by the caller — a sentence a human approved at a
            # gate, on a run that is skipping this one. Classified at the API
            # boundary like any other text the client supplies; nothing is
            # regenerated, so the panel is told exactly what was approved. This
            # is also what makes a repeat run cost no rewrite.
            return {}
        draft = generator.draft(words=words)
        if draft.refusal is not None:
            raise RolePlayRefused(draft.refusal)
        return {"instruction": draft.instruction}

    def select(state: EvaluateState) -> EvaluateState:
        """Draw the panel from the settled reading. Pure SQL, nothing paid.

        The query arrives settled — built from the controls at the endpoint, or
        rebuilt there from the gate's edit — so this node never interprets
        anything. It only retrieves, and reports a shortfall when the pool has
        fewer matching people than the panel asked for.
        """
        settled = state["query"]
        target = state.get("edited") or settled
        panel = retrieve_panel(conn, target, size=state["size"], seed=PANEL_SEED)
        if not panel and state.get("panel") is None:
            # Nothing to show and nothing to approve: the run never starts.
            raise EmptyPanel(
                f"no persona matches this target (size {state['size']} requested)"
            )
        if not panel:
            # An *edit* that matches nobody must not raise. The edit is already
            # in state, so every resume would fail here and the run would be
            # unrecoverable. Go back to the gate reading zero instead.
            return {
                "query": target,
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
        # Readings explain the *unchanged* reading, so they are kept when it is
        # and dropped when an edit replaced it; a shortfall is about who was
        # actually seated, so it is recomputed either way.
        kept = list(state.get("notices", [])) if target == settled else []
        return {
            "query": target,
            "panel": panel,
            "notices": kept + list(shortfall_notices(panel, state["size"])),
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
            return {
                "decision": "adjust",
                "edited": decision.query or state["query"],
                "refused": None,
            }
        return {"decision": "accept"} | _approved(state, decision.instruction)

    def _approved(state: EvaluateState, edited: str | None) -> EvaluateState:
        """Settle which sentence the panel is told.

        The gate's field is editable and that edit *is* the human-in-the-loop, so
        it reaches a panel prompt without ever passing the generator. Two layers
        cover it, and they sit in different places on purpose:

        - the model classifier runs at the API boundary, above the charge for the
          panel, because whether a sentence may run is also the decision about
          whether it costs a run (094: refusals never consume runs);
        - the deterministic backstop runs here, last, closest to the prompt it
          protects — no model call, so it costs nothing to apply on every path.

        An untouched or cleared field settles without either: the draft was
        classified when it was written, and clearing the field is a decision
        rather than a sentence to judge.
        """
        settled = state.get("instruction", "")
        if edited is None or edited == settled:
            return {}
        if not edited.strip():
            return {"instruction": "", "refused": None}
        checked = without_task_talk(RolePlayOutcome(instruction=edited))
        if checked.refusal is not None:
            # Reached only if the classifier above passed something the word list
            # catches. Back to the gate rather than onward: the reader can fix it.
            return {"decision": "adjust", "refused": checked.refusal}
        return {"instruction": checked.instruction, "refused": None}

    def vote(state: EvaluateState) -> EvaluateState:
        """The one paid node. The vote loop itself is unchanged.

        The headlines are checked here because this is where they first reach a
        model, and before the panel is asked, so refused text costs no votes.
        """
        screen_inputs(screener, list(state["variants"].values()))
        return {
            "collected": run_vote_loop(
                conn,
                state["panel"],
                variants=state["variants"],
                llm=llm,
                enacted=state.get("instruction", ""),
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
                enacted=state.get("instruction", ""),
            )
        }

    def after_confirm(state: EvaluateState) -> Literal["select", "vote"]:
        """Route to `vote` only for an accepted, non-empty panel.

        An accept with nobody seated has nobody to ask, so it returns to the
        gate instead.
        """
        if state.get("decision") == "adjust" or not state["panel"]:
            return "select"
        return "vote"

    builder = StateGraph(EvaluateState)
    builder.add_node("roleplay", roleplay)
    builder.add_node("select", select)
    builder.add_node("confirm", confirm)
    builder.add_node("vote", vote)
    builder.add_node("assemble", assemble)
    builder.add_edge(START, "roleplay")
    builder.add_edge("roleplay", "select")
    builder.add_edge("select", "confirm")
    builder.add_conditional_edges("confirm", after_confirm)
    builder.add_edge("vote", "assemble")
    builder.add_edge("assemble", END)
    return builder.compile(checkpointer=checkpointer)
