"use client";

import { useEffect, useState } from "react";

import { runProgress } from "../lib/api";
import { KICKER } from "../lib/styles";

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

/** ~13 asks over the ~40 s a prod run measures (010a) — enough to watch the
 *  count climb without turning the wait into load. */
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
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const clock = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(clock);
  }, []);

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
      // The clock until the first count lands, so the line is alive from the
      // first second; a real number the moment there is one.
      sub: voted === null ? `${seconds}s` : `${voted} of ${size}`,
    },
    { label: "Verdict computed", done: false, sub: "" },
  ];

  return (
    <div role="status" aria-live="polite" className="flex flex-col gap-6 py-8">
      <div className="flex flex-col gap-1 text-center">
        <p className={KICKER}>The panel is reading</p>
        <h2>{size} readers, one line each.</h2>
      </div>
      <div className="mx-auto flex w-full max-w-xl flex-col">
        {lines.map(({ label, done, sub }) => (
          <p
            key={label}
            className={`flex items-baseline justify-between gap-4 border-b border-line py-[13px] text-[13px] font-semibold uppercase tracking-[0.08em] ${
              done ? "text-ink" : "text-ink-3"
            }`}
          >
            <span>
              {done ? "✓ " : ""}
              {label}
            </span>
            {sub !== "" && (
              <span className="text-[11px] font-normal normal-case tracking-[0.04em] text-ink-3">
                {sub}
              </span>
            )}
          </p>
        ))}
      </div>
      <p className="text-center text-sm font-light text-ink-2">
        A run of this size usually takes under a minute.
      </p>
    </div>
  );
}
