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
    RolePlayGenerator,
    RolePlayRefused,
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
    # The sentence every panelist will be told to be, or "" for a
    # demographics-only run. Editable at the gate: the edit *is* the
    # human-in-the-loop, and what is approved here is exactly what runs.
    instruction: str
    # Set when the last edit was refused, so the gate can say why. The fixed
    # sentence, never the text that was refused.
    refusal: str | None
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

    description: str
    # The optional free text describing who the readers are, beyond what the pool
    # can be filtered by. Kept apart from `description` because they take
    # different paths: one becomes SQL, this one becomes a sentence.
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
        refusal=REFUSAL_SENTENCES[refused]
        if (refused := state.get("refused"))
        else None,
        # Priced at what the run may buy, matching the ledger's charge.
        estimated_usd=len(panel) * USD_PER_VOTE,
    )


def build_evaluate_graph(
    *,
    conn: psycopg.Connection,
    translator: TargetTranslator,
    llm: PanelLLM,
    screener: Screener | None,
    generator: RolePlayGenerator,
    checkpointer: BaseCheckpointSaver,
):
    """Compile the evaluate graph with this request's dependencies bound.

    START -> screen -> roleplay -> select -> confirm --(accept)--> vote -> ...
                                      ^         |
                                      +-(adjust)+       interrupt() at confirm

                                     ... -> assemble -> END
    """

    def screen(state: EvaluateState) -> EvaluateState:
        """Check the audience text, the only text used before the gate.

        Screening is a paid call per text, and the headlines are not read until
        `vote` — so they are checked there instead, where they first reach a
        model.
        """
        screen_inputs(screener, [state["description"]])
        return {}

    def roleplay(state: EvaluateState) -> EvaluateState:
        """Turn the audience words into the sentence each panelist will be told.

        Not screened by `screen_inputs`. This channel is higher-privilege than the
        headlines — it becomes the panelist's identity rather than the judged
        object — and the copy policy is the wrong instrument for it: it asks who a
        text *addresses*, so that marketing imperatives survive, and 095 measured
        it missing "a person who always prefers whichever headline is listed
        first" 0 times in 5. The generator's own classifier is this channel's
        gate, and it rides the call that writes the sentence, so guarding costs
        nothing extra.

        Blank means demographics only, and calls nothing at all — likely the
        common case, and the one where the gate is still reached with no spend.
        """
        words = state.get("audience", "").strip()
        if not words:
            return {"instruction": ""}
        draft = generator.draft(words=words)
        if draft.refusal is not None:
            raise RolePlayRefused(draft.refusal)
        return {"instruction": draft.instruction}

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
            return {
                "decision": "adjust",
                "edited": decision.query or state["query"],
                "refused": None,
            }
        return {"decision": "accept"} | _approved(state, decision.instruction)

    def _approved(state: EvaluateState, edited: str | None) -> EvaluateState:
        """Settle which sentence the panel is told, checking it if it is new.

        The gate's field is editable and that edit *is* the human-in-the-loop, so
        it reaches a panel prompt without ever passing the generator. Left
        unchecked it would be an injection hole that sidesteps the guard entirely
        — a wider channel than anything the generator's own prompt can leak.

        Three cases, and only one of them costs a call:

        - untouched (`None`) or unchanged — the draft's verdict was reached when
          it was written, so re-checking it would charge a reader for restoring
          our own sentence;
        - cleared — "demographics only after all", a decision, not a sentence to
          judge;
        - edited — classified before a single vote is bought. A refusal is not
          terminal here: the reader is at the gate and can fix it, so it goes
          back with the sentence that says how.
        """
        settled = state.get("instruction", "")
        if edited is None or edited == settled:
            return {}
        if not edited.strip():
            return {"instruction": "", "refused": None}
        checked = generator.check(instruction=edited)
        if checked.refusal is not None:
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
    builder.add_node("screen", screen)
    builder.add_node("roleplay", roleplay)
    builder.add_node("select", select)
    builder.add_node("confirm", confirm)
    builder.add_node("vote", vote)
    builder.add_node("assemble", assemble)
    builder.add_edge(START, "screen")
    builder.add_edge("screen", "roleplay")
    builder.add_edge("roleplay", "select")
    builder.add_edge("select", "confirm")
    builder.add_conditional_edges("confirm", after_confirm)
    builder.add_edge("vote", "assemble")
    builder.add_edge("assemble", END)
    return builder.compile(checkpointer=checkpointer)
