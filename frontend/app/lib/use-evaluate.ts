"use client";

import { useState } from "react";

import {
  evaluate,
  resumeEvaluate,
  type EvaluateInput,
  type EvaluateOutcome,
  type EvaluateResponse,
  type PanelPreview,
  type TargetQuery,
} from "./api";

/** The request's four phases as one value, so contradictory combinations —
 *  loading with a stale result, an error beside a success — cannot be
 *  represented, only replaced. */
export type EvaluateState =
  | { phase: "idle" }
  | { phase: "loading" }
  /** Holding at the panel gate: nothing bought yet, waiting for a person to
   *  accept the reading or edit it. */
  | { phase: "gated"; threadId: string; preview: PanelPreview }
  | { phase: "error"; message: string }
  | { phase: "done"; result: EvaluateResponse };

export function useEvaluate() {
  const [state, setState] = useState<EvaluateState>({ phase: "idle" });

  function land(outcome: EvaluateOutcome): void {
    setState(
      outcome.status === "paused"
        ? {
            phase: "gated",
            threadId: outcome.thread_id,
            preview: outcome.preview,
          }
        : { phase: "done", result: outcome },
    );
  }

  async function attempt(work: () => Promise<EvaluateOutcome>): Promise<void> {
    setState({ phase: "loading" });
    try {
      land(await work());
    } catch (error) {
      setState({
        phase: "error",
        message: error instanceof Error ? error.message : "Request failed",
      });
    }
  }

  async function submit(request: EvaluateInput): Promise<void> {
    await attempt(() => evaluate(request));
  }

  /** Answer the gate. `accept` spends; `adjust` re-seats from an edited
   *  reading and returns to the gate, since nobody has accepted that one yet. */
  async function answerGate(
    action: "accept" | "adjust",
    query?: TargetQuery,
  ): Promise<void> {
    if (state.phase !== "gated") return;
    const threadId = state.threadId;
    await attempt(() => resumeEvaluate({ threadId, action, query }));
  }

  // Back to the question without touching the answers: the fields live in the
  // form's own state, so a second run starts from what was asked rather than
  // from blank — changing one headline is the common one.
  function reset(): void {
    setState({ phase: "idle" });
  }

  return { state, submit, answerGate, reset };
}
