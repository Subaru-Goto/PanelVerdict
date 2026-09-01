"use client";

import { useEffect, useState } from "react";

import { runProgress } from "../lib/api";
import { KICKER } from "../lib/styles";
import { StepLine } from "./step-line";

/** The waiting screen for a paid run (021/#126): the prototype's step stream,
 *  with the vote line's number polled off the vote ledger — rows the pipeline
 *  was already writing — so the count is a fact, never an animation.
 *
 *  Same three lines as the demo replay, for the same reason (061): they are
 *  the graph's own nodes in the order they run, and screening happens inside
 *  the vote step. The demo prints its captured seconds; a live run has no
 *  seconds until they have happened, so it prints the count instead.
 *
 *  "Panel assembled" is claimed done from the first frame, and honestly so:
 *  the sample is seeded, so the panel this run seats is the one the gate
 *  showed when this reading was approved — person for person.
 */

/** ~15 asks over the longest vote step yet measured — 45.3 s for a full
 *  200-vote buy (the free-delivery capture's own step_seconds,
 *  backend/app/data/demo, 2026-09-01) — enough to watch the count climb
 *  without turning the wait into load. */
const POLL_MS = 3000;

export default function RunStream({
  threadId,
  size,
}: {
  threadId: string;
  /** Seats, not requested size: the number the gate showed. */
  size: number;
}) {
  const [voted, setVoted] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    const ask = () =>
      runProgress(threadId).then(
        (progress) => {
          if (live) setVoted(progress.votes_recorded);
        },
        () => {
          // A failed poll keeps the last count. The run itself is the blocking
          // request elsewhere — this number must never be able to break it.
        },
      );
    void ask();
    const timer = setInterval(ask, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [threadId]);

  const lines = [
    { label: "Panel assembled", done: true, sub: `${size} readers` },
    {
      label: "Votes returning",
      done: false,
      // Nothing until the first count lands — an empty slot is honest, an
      // invented clock or zero is not. A real number the moment there is one.
      sub: voted === null ? undefined : `${voted} of ${size}`,
    },
    { label: "Verdict computed", done: false, sub: undefined },
  ];

  return (
    <div role="status" aria-live="polite" className="flex flex-col gap-6 py-8">
      <div className="flex flex-col gap-1 text-center">
        <p className={KICKER}>The panel is reading</p>
        <h2>{size} readers, one line each.</h2>
      </div>
      <div className="mx-auto flex w-full max-w-xl flex-col">
        {lines.map(({ label, done, sub }) => (
          <StepLine key={label} label={label} done={done} sub={sub} />
        ))}
      </div>
      {/* Two claims, both measured (the captured fixtures' step_seconds,
          backend/app/data/demo, 2026-09-01): the full 200-vote buy took
          45.3 s, and decisive runs stopped inside 5 s having bought 50. The
          second sentence is the ticket's carried constraint — an early stop
          must read as an answer, not an interruption — said before it
          happens, so a count that halts short of the size reads as the panel
          being sure, not the run stalling. */}
      <p className="text-center text-sm font-light text-ink-2">
        A run of this size usually takes under a minute — and stops early once
        the answer is clear, leaving the rest of its votes unasked.
      </p>
    </div>
  );
}
