"use client";

import { useEffect, useRef, useState } from "react";

import { onRunsChanged, remainingRuns } from "../lib/api";
import {
  mountGoogleButton,
  onAuthChange,
  signInAvailable,
  signOut,
} from "../lib/auth";

/** Signing in, and what it buys you today (063/#158, 092/#197).
 *
 * The smallest control that makes the flow reachable. Where this eventually
 * sits — and what it looks like — belongs to the redesign (093/#198); what it
 * must keep doing is here: never appear in a build that cannot sign anyone in,
 * and show the reader their own remaining runs rather than the shared pool's.
 */
const LINK_CLASS =
  "underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";

export default function SignIn() {
  // Three states, not two: until the client has looked for a stored session
  // nobody knows. Starting at `false` would flash "sign in" — and mount
  // Google's button — at a visitor who is already signed in.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [runsLeft, setRunsLeft] = useState<number | null>(null);
  const buttonSlot = useRef<HTMLSpanElement | null>(null);
  const available = signInAvailable();

  useEffect(() => onAuthChange(setSignedIn), []);

  useEffect(() => {
    if (signedIn !== false || !available || buttonSlot.current === null) return;
    // Google renders its own button into the slot. Failure leaves the slot
    // empty rather than throwing into React: an unavailable identity provider
    // is not a reason for the rest of the page to stop working.
    void mountGoogleButton(buttonSlot.current).catch(() => {});
  }, [signedIn, available]);

  useEffect(() => {
    if (signedIn !== true) return;
    // Re-read whenever a run spends one, not only when the session changes.
    // `live` guards the late answer: signing out while this is in flight would
    // otherwise write a count belonging to a session that has ended. Clearing
    // on the way *out* is the sign-out handler's job rather than this effect's
    // — a synchronous setState here would cascade a render for no reason.
    let live = true;
    const read = () =>
      void remainingRuns().then((left) => {
        if (live) setRunsLeft(left);
      });
    read();
    const stop = onRunsChanged(read);
    return () => {
      live = false;
      stop();
    };
  }, [signedIn]);

  // A build with no Supabase project — local development, CI — renders as it
  // did before this existed. A button that cannot work is worse than none.
  // Same for the moment before the session is known: nothing, rather than a
  // guess that has to be taken back.
  if (!available || signedIn === null) return null;

  return (
    <p className="flex items-center gap-3 text-sm text-zinc-600 dark:text-zinc-400">
      {signedIn ? (
        <>
          {runsLeft !== null && (
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
            className={LINK_CLASS}
          >
            Sign out
          </button>
        </>
      ) : (
        <>
          <span>Running a test costs money, so it asks who you are.</span>
          <span ref={buttonSlot} />
        </>
      )}
    </p>
  );
}
