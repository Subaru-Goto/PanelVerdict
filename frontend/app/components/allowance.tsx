"use client";

import { useEffect, useState } from "react";

import { onRunsChanged, remainingRuns } from "../lib/api";

/** The reader's own remaining runs (063/#158), beside the button that spends
 *  one — the prototype seats the allowance in the actions row, not the
 *  header, because the number matters at the moment of spending. Their own
 *  count, never the shared pool's: that one is withheld so nobody gets a
 *  progress bar for draining it.
 */
export default function Allowance() {
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    // Re-read whenever a run spends one: the figure is a budget, and a stale
    // one would still read "3 runs left" right after the run that made it 2.
    let live = true;
    const read = () =>
      void remainingRuns().then((n) => {
        if (live) setLeft(n);
      });
    read();
    const stop = onRunsChanged(read);
    return () => {
      live = false;
      stop();
    };
  }, []);

  // A failed read is not a zero: claiming "0 runs left" would tell someone
  // they are out when they are not.
  if (left === null) return null;
  return (
    <span className="text-[12.5px] font-light text-ink-3">
      {left === 0
        ? "No runs left today"
        : left === 1
          ? "1 run left today"
          : `${left} runs left today`}
    </span>
  );
}
