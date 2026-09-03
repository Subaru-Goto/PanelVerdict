"use client";

import { useEffect, useState } from "react";

import {
  type AccountFigures,
  accountFigures,
  onAccountChanged,
} from "../lib/api";
import { noticeClass } from "./notice-style";

/** The reader's own figures beside the button that spends one (063/#158):
 *  the prototype seats the allowance in the actions row, not the header,
 *  because the number matters at the moment of spending. Their own count,
 *  never the shared pool's: that one is withheld so nobody gets a progress
 *  bar for draining it.
 *
 *  A full rail is said here too, before the run (124/#291): the save cap
 *  refuses after the money is spent, and the reader should hear it while the
 *  run can still be skipped. The run stays allowed; this is a warning.
 */
export default function Allowance() {
  const [figures, setFigures] = useState<AccountFigures | null>(null);

  useEffect(() => {
    // Re-read whenever the figures move: a run spends one, a delete in the
    // rail makes room. A stale figure would still read "3 runs left" right
    // after the run that made it 2.
    let live = true;
    const read = () =>
      void accountFigures().then((next) => {
        if (live) setFigures(next);
      });
    read();
    const stop = onAccountChanged(read);
    return () => {
      live = false;
      stop();
    };
  }, []);

  // A failed read is not a zero: claiming "0 runs left" would tell someone
  // they are out when they are not, and "your rail is full" when it is not.
  if (figures === null) return null;
  const {
    runs_remaining: left,
    saved_tests: saved,
    saved_tests_cap: cap,
  } = figures;
  const railFull = saved !== undefined && cap !== undefined && saved >= cap;
  return (
    <>
      {railFull && (
        // Its own line above the button (`order-first basis-full` in the
        // wrapping row). The sentence is the twin of the post-run warning in
        // backend/app/main.py: the limit, never the count, and the remedy
        // only while there is a cap to make room under. Change both together.
        <p
          role="status"
          className={`order-first basis-full ${noticeClass("warning")}`}
        >
          {`Your rail is full: an account keeps at most ${cap} saved test${cap === 1 ? "" : "s"}, so this test will not be saved.`}
          {cap > 0 && " Delete a saved test to make room."}
        </p>
      )}
      <span className="text-[12.5px] font-light text-ink-3">
        {left === 0
          ? "No runs left today"
          : left === 1
            ? "1 run left today"
            : `${left} runs left today`}
      </span>
    </>
  );
}
