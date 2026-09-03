"use client";

import { useEffect, useState } from "react";

import { runDemo, type DemoResult } from "../lib/api";
import { AI_SYSTEM_DISCLOSURE, DEMO_REPLAY_NOTE } from "../lib/disclosure";
import { KICKER } from "../lib/styles";
import Report from "./report";
import { ReportBoundary } from "./report-boundary";
import { StepLine, elapsed } from "./step-line";
import Stepper from "./stepper";

/** The demo (061/#156): a captured run replayed through the real graph,
 *  played back as the steps it actually took, then the real report.
 *
 *  The printed seconds are the captured run's own — inventing durations is
 *  forbidden. The *wait* between steps is presentation pacing, clamped so a
 *  45-second vote does not hold a visitor hostage and a 90 ms selection is
 *  visible at all; the label carries the truth.
 */

/** Graph nodes worth a line, in the order they ran. `roleplay` and `confirm`
 *  are skipped: on a demo both are no-ops measured in single milliseconds —
 *  no audience words to draft, no gate to hold at. */
const REPLAY_STEPS: { node: string; label: string }[] = [
  { node: "select", label: "Panel assembled" },
  { node: "vote", label: "Votes returning" },
  { node: "assemble", label: "Verdict computed" },
];

/** The wait before the next step lights up. Clamped to the prototype's own
 *  replay range — REPLAY_MS spans 600–2600 ms (prototype.html) — so a
 *  45-second vote is printed truthfully but not sat through, and a 90 ms
 *  selection is on screen long enough to read. */
function paced(seconds: number): number {
  return Math.min(Math.max(seconds * 1000, 600), 2600);
}

type Playback =
  | { phase: "fetching" }
  | { phase: "playing"; result: DemoResult; done: number }
  | { phase: "done"; result: DemoResult }
  | { phase: "error"; message: string };

export default function DemoReplay({ demoCase }: { demoCase: string }) {
  const [state, setState] = useState<Playback>({ phase: "fetching" });

  // No reset on a changed case: the caller keys this component by the case,
  // so a different sample is a fresh mount with fresh state.
  useEffect(() => {
    let live = true;
    runDemo(demoCase).then(
      (result) => {
        if (live) setState({ phase: "playing", result, done: 0 });
      },
      (error: Error) => {
        if (live) setState({ phase: "error", message: error.message });
      },
    );
    return () => {
      live = false;
    };
  }, [demoCase]);

  useEffect(() => {
    if (state.phase !== "playing") return;
    const seconds =
      state.result.step_seconds[REPLAY_STEPS[state.done].node] ?? 0;
    const timer = setTimeout(
      () =>
        // Functional, so the transition reads the state the timer fires
        // against rather than the render it was scheduled in.
        setState((now) =>
          now.phase !== "playing"
            ? now
            : now.done + 1 >= REPLAY_STEPS.length
              ? { phase: "done", result: now.result }
              : { ...now, done: now.done + 1 },
        ),
      paced(seconds),
    );
    return () => clearTimeout(timer);
  }, [state]);

  const chrome = (
    <Stepper current={state.phase === "done" ? "Verdict" : "Voting"} />
  );
  if (state.phase === "error") {
    return (
      <div className="flex flex-col gap-6">
        {chrome}
        <p className="text-red">{state.message}</p>
      </div>
    );
  }
  if (state.phase === "fetching") {
    return (
      <div className="flex flex-col gap-6">
        {chrome}
        <p className="text-sm text-ink-2">Fetching the sample run…</p>
      </div>
    );
  }

  const { result } = state;
  const replayLine = `A real panel’s run from ${result.captured_at}, replayed — ${DEMO_REPLAY_NOTE}`;

  if (state.phase === "done") {
    return (
      <div className="flex flex-col gap-4">
        {chrome}
        <p className="text-sm text-ink-2">{replayLine}</p>
        <p className="text-sm text-ink-3">{AI_SYSTEM_DISCLOSURE}</p>
        {/* No stored test to refetch on the demo: Refresh replays the sample. */}
        <ReportBoundary onRefresh={() => window.location.reload()}>
          <Report result={result} analyst="locked" />
        </ReportBoundary>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 py-8">
      {chrome}
      <div className="flex flex-col gap-1 text-center">
        <p className={KICKER}>The panel is reading</p>
        <p className="text-sm text-ink-2">{replayLine}</p>
        <p className="text-xs text-ink-3">{AI_SYSTEM_DISCLOSURE}</p>
      </div>
      <div className="mx-auto flex w-full max-w-xl flex-col">
        {REPLAY_STEPS.map(({ node, label }, i) => (
          <StepLine
            key={node}
            label={label}
            done={i < state.done}
            // A node the fixture never timed shows nothing — a printed zero
            // would be an invented duration.
            sub={
              result.step_seconds[node] !== undefined
                ? elapsed(result.step_seconds[node])
                : undefined
            }
          />
        ))}
      </div>
    </div>
  );
}
