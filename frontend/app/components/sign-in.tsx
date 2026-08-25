"use client";

import { useEffect, useState } from "react";

import { remainingRuns } from "../lib/api";
import { onAuthChange, signIn, signInAvailable, signOut } from "../lib/auth";

/** Signing in, and what it buys you today (063/#158, 092/#197).
 *
 * The smallest control that makes the flow reachable. Where this eventually
 * sits — and what it looks like — belongs to the redesign (093/#198); what it
 * must keep doing is here: never appear in a build that cannot sign anyone in,
 * and show the reader their own remaining runs rather than the shared pool's.
 */
export default function SignIn() {
  const [signedIn, setSignedIn] = useState(false);
  const [runsLeft, setRunsLeft] = useState<number | null>(null);
  const available = signInAvailable();

  useEffect(() => onAuthChange(setSignedIn), []);

  useEffect(() => {
    if (!signedIn) return;
    // `live` guards the late answer: signing out while this is in flight would
    // otherwise write a count belonging to a session that has ended. Clearing
    // on the way *out* is the sign-out handler's job rather than this effect's
    // — a synchronous setState here would cascade a render for no reason.
    let live = true;
    void remainingRuns().then((left) => {
      if (live) setRunsLeft(left);
    });
    return () => {
      live = false;
    };
  }, [signedIn]);

  // A build with no Supabase project — local development, CI — renders as it
  // did before this existed. A button that cannot work is worse than none.
  if (!available) return null;

  return (
    <p className="flex items-center gap-3 text-sm text-zinc-600 dark:text-zinc-400">
      {signedIn ? (
        <>
          {signedIn && runsLeft !== null && (
            <span>
              {runsLeft} {runsLeft === 1 ? "run" : "runs"} left today
            </span>
          )}
          <button
            type="button"
            onClick={() => {
              // Cleared here, not in an effect: the count belongs to the
              // session being ended, and it must not flash back on the next
              // sign-in before the fresh one arrives.
              setRunsLeft(null);
              void signOut();
            }}
            className="underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            Sign out
          </button>
        </>
      ) : (
        <>
          <span>Running a test costs money, so it asks who you are.</span>
          <button
            type="button"
            onClick={() => void signIn()}
            className="underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            Sign in with Google
          </button>
        </>
      )}
    </p>
  );
}
