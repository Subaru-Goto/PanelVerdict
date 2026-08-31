"use client";

import { useState } from "react";

import {
  evaluate,
  resumeEvaluate,
  type EvaluateInput,
  type EvaluateOutcome,
  type EvaluateResponse,
  type PanelPreview,
  type PanelEdit,
} from "./api";

/** The request's four phases as one value, so contradictory combinations —
 *  loading with a stale result, an error beside a success — cannot be
 *  represented, only replaced. */
export type EvaluateState =
  | { phase: "idle" }
  | { phase: "loading" }
  /** Holding at the panel gate: nothing bought yet, waiting for a person to
   *  accept the reading or edit it. `notice` is the backend's fixed sentence
   *  when the last answer was refused — the run is still paused there, so the
   *  gate stays up for the reader to act on it. `resuming` marks an answer in
   *  flight, so the page can prove the run is alive. */
  | {
      phase: "gated";
      threadId: string;
      preview: PanelPreview;
      notice?: string;
      resuming?: boolean;
    }
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
   *  reading and returns to the gate, since nobody has accepted that one yet.
   *
   *  Not routed through `attempt`: a refused answer leaves the run paused on
   *  the server, so falling to the error phase here would throw away a live
   *  thread — and the reader's edit with it. The gate stays up and shows the
   *  refusal's remedy instead. */
  async function answerGate(
    action: "accept" | "adjust",
    query?: PanelEdit,
    instruction?: string,
  ): Promise<void> {
    if (state.phase !== "gated") return;
    const { threadId, preview } = state;
    setState({ phase: "gated", threadId, preview, resuming: true });
    try {
      land(await resumeEvaluate({ threadId, action, query, instruction }));
    } catch (error) {
      setState({
        phase: "gated",
        threadId,
        preview,
        notice:
          error instanceof Error ? error.message : "Request failed",
      });
    }
  }

  // Back to the question without touching the answers: the fields live in the
  // form's own state, so a second run starts from what was asked rather than
  // from blank — changing one headline is the common one.
  function reset(): void {
    setState({ phase: "idle" });
  }

  /** Render a report this hook did not run: one reopened from the rail
   *  (117/#252), or recovered after a crash lost the one on screen.
   *
   *  It lands in the same `done` phase a fresh run lands in, on purpose — a
   *  stored report is the report, so a second render path for it would be a
   *  second place for the report to be drawn wrongly. */
  function show(result: EvaluateResponse): void {
    setState({ phase: "done", result });
  }

  return { state, submit, answerGate, reset, show };
}
