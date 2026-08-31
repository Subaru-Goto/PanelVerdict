"use client";

import { useRef, useState } from "react";

import {
  evaluate,
  resumeEvaluate,
  type EvaluateInput,
  type EvaluateOutcome,
  type EvaluateResponse,
  type PanelPreview,
  type PanelEdit,
} from "./api";
import { readingKey, settledEdit } from "./reading";

/** A reading a human accepted at the gate, remembered so the gate fires once
 *  per audience (077/#167): a later run whose key matches rides as
 *  `readingAccepted`, carrying the approved instruction. The preview is kept
 *  for the echo under the form — the reader can see what stands approved. */
export type AcceptedReading = {
  key: string;
  instruction: string;
  preview: PanelPreview;
};

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
  /** `epoch` counts arrivals at this phase, and exists to be a React `key` on
   *  the report. Replacing one report with another *without leaving this phase*
   *  — which is what reopening a stored test does — reconciles the report in
   *  place, so the analyst's thread id, its transcript and its
   *  already-opened flag all survive into a report they are not about
   *  (117/#252). Counting every arrival rather than only the reopen keeps the
   *  key correct without depending on which transitions happen to remount. */
  | { phase: "done"; result: EvaluateResponse; epoch: number };

export function useEvaluate() {
  const [state, setState] = useState<EvaluateState>({ phase: "idle" });

  const epoch = useRef(0);

  // The run paused at the gate while the reader is back on the form. Kept so
  // the next preview *resumes* it instead of starting over — a restart re-runs
  // the paid, non-reproducible audience rewrite and can hand back a different
  // reading than the one just rejected (077, decided 2026-08-31). The words
  // are kept beside the id because only an unchanged audience may ride:
  // rephrasing is a new reading and legitimately starts fresh.
  const paused = useRef<{ threadId: string; audience: string } | null>(null);

  // What the last request asked, so an accept can be remembered under the key
  // of the audience it approved.
  const asked = useRef<EvaluateInput | null>(null);

  // Rendered state rather than a ref: the form shows the echo line for it.
  const [accepted, setAccepted] = useState<AcceptedReading | null>(null);

  function land(outcome: EvaluateOutcome): void {
    setState(
      outcome.status === "paused"
        ? {
            phase: "gated",
            threadId: outcome.thread_id,
            preview: outcome.preview,
          }
        : { phase: "done", result: outcome, epoch: ++epoch.current },
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
    asked.current = request;
    const held = paused.current;
    paused.current = null;

    // A run holding at the gate outranks everything, standing approval
    // included: skipping past it would orphan the thread and buy a second
    // preview for the same test. Unchanged words may ride it — controls and
    // headlines go along, the reading is not re-enacted. Changed words start
    // fresh: rephrasing is a new reading.
    if (held !== null && held.audience === (request.audience ?? "").trim()) {
      await attempt(async () => {
        try {
          return await resumeEvaluate({
            threadId: held.threadId,
            action: "adjust",
            query: settledEdit(request),
            headlineA: request.headlineA,
            headlineB: request.headlineB,
          });
        } catch (error) {
          // Only a pause that is truly gone falls back to a fresh run — the
          // backend's own sentences for expiry (410) and no-such-run (404).
          // Anything else surfaces: a quiet restart would re-run the paid,
          // non-reproducible rewrite behind the reader's back.
          const gone =
            error instanceof Error &&
            /expired|no run is waiting/.test(error.message);
          if (!gone) throw error;
          return await evaluate(request);
        }
      });
      return;
    }

    // The gate fires once per audience: a key match means this exact reading
    // — every control and the words — was approved, so the approval rides.
    if (accepted !== null && readingKey(request) === accepted.key) {
      await attempt(() =>
        evaluate(
          accepted.instruction === ""
            ? // A cleared instruction was the approval: demographics only
              // after all. The skip contract requires an instruction whenever
              // words ride, so the honest translation is no words at all —
              // the run is exactly what was approved.
              { ...request, audience: "", readingAccepted: true }
            : {
                ...request,
                readingAccepted: true,
                instruction: accepted.instruction,
              },
        ),
      );
      return;
    }

    await attempt(() => evaluate(request));
  }

  /** Leave the gate for the form without abandoning the run: the pause is
   *  kept, and the next preview with these words resumes it. */
  function adjustAudience(): void {
    if (state.phase !== "gated") return;
    paused.current = {
      threadId: state.threadId,
      audience: (asked.current?.audience ?? "").trim(),
    };
    setState({ phase: "idle" });
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
      const outcome = await resumeEvaluate({
        threadId,
        action,
        query,
        instruction,
      });
      if (action === "accept" && outcome.status === "complete") {
        // This exact reading now stands approved: later runs under the same
        // key skip the gate. Untouched rides as absence, so what stands is
        // the draft the reader saw.
        setAccepted({
          // `asked` is always set: the only road to the gate is a submit.
          // The empty-key fallback exists for the type, and can never match
          // a real reading — `readingKey` always returns an object literal.
          key: asked.current !== null ? readingKey(asked.current) : "",
          instruction: instruction ?? preview.instruction,
          preview,
        });
      }
      land(outcome);
    } catch (error) {
      setState({
        phase: "gated",
        threadId,
        preview,
        notice: error instanceof Error ? error.message : "Request failed",
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
    setState({ phase: "done", result, epoch: ++epoch.current });
  }

  /** Land on the error phase for a failure this hook did not produce — a
   *  stored test that would not open. Same phase as a failed run, on purpose:
   *  one place draws errors. */
  function fail(message: string): void {
    setState({ phase: "error", message });
  }

  /** Withdraw the standing approval: the next submit gates again. */
  function forgetReading(): void {
    setAccepted(null);
  }

  return {
    state,
    submit,
    answerGate,
    reset,
    show,
    fail,
    adjustAudience,
    accepted,
    forgetReading,
  };
}
