"use client";

import { useEffect, useRef, useState } from "react";

import {
  displayName,
  mountGoogleButton,
  onAuthChange,
  signInAvailable,
  signOut,
} from "../lib/auth";

/** Signing in and out, as the prototype's nav settles it (063/#158, 092/#197):
 * signed out, Google's own button; signed in, the "who" pill — the reader's
 * name with an initials disc — whose click is the sign-out. The remaining-runs
 * count lives beside the run button (`Allowance`), where spending happens,
 * not here. Never appears in a build that cannot sign anyone in.
 */

/** First letters of the first two words — "Sam O." wears "SO". */
function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? "")
    .join("");
}

export default function SignIn() {
  // Three states, not two: until the client has looked for a stored session
  // nobody knows. Starting at `false` would flash "sign in" — and mount
  // Google's button — at a visitor who is already signed in.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [name, setName] = useState<string | null>(null);
  const buttonSlot = useRef<HTMLSpanElement | null>(null);
  const available = signInAvailable();

  useEffect(
    () =>
      onAuthChange((value) => {
        setSignedIn(value);
        // Cleared on the way out, not at the click: the pill must stay up as
        // sign-out's feedback until the session event lands — and a cleared
        // name here cannot flash into the next session's pill.
        if (!value) setName(null);
      }),
    [],
  );

  useEffect(() => {
    if (signedIn !== false || !available || buttonSlot.current === null) return;
    // Google renders its own button into the slot. Failure leaves the slot
    // empty rather than throwing into React: an unavailable identity provider
    // is not a reason for the rest of the page to stop working.
    void mountGoogleButton(buttonSlot.current).catch(() => {});
  }, [signedIn, available]);

  useEffect(() => {
    if (signedIn !== true) return;
    // `live` guards the late answer: signing out while this read is in
    // flight must not stamp the ended session's name onto the next one.
    let live = true;
    displayName().then(
      (reported) => {
        // A session with no readable name still owns the header's only
        // sign-out control, so the pill gets a plain label rather than
        // vanishing (and a failed read is treated the same, below).
        if (live) setName(reported ?? "Signed in");
      },
      () => {
        if (live) setName("Signed in");
      },
    );
    return () => {
      live = false;
    };
  }, [signedIn]);

  // A build with no Supabase project — local development, CI — renders as it
  // did before this existed. A button that cannot work is worse than none.
  // Same for the moment before the session is known: nothing, rather than a
  // guess that has to be taken back. And the same again for the moment before
  // the name is known: a pill with a blank disc reads as broken, not loading.
  if (!available || signedIn === null) return null;

  if (signedIn) {
    if (name === null) return null;
    return (
      <p className="flex items-center text-sm">
        <button
          type="button"
          // The pill is the sign-out, as the prototype has it — the label
          // names the action, the text names the person.
          aria-label={`Sign out (${name})`}
          title="Sign out"
          onClick={() => void signOut()}
          // cursor-pointer because Tailwind's preflight defaults buttons to
          // cursor:default, and the prototype's .who is pointer.
          className="flex cursor-pointer items-center gap-[9px] rounded-pill border border-line py-[5px] pl-3.5 pr-1.5 text-[13px] font-medium"
        >
          {name}
          <span
            aria-hidden
            className="grid h-6 w-6 place-items-center rounded-full bg-ink text-[11px] font-semibold tracking-[0.02em] text-surface"
          >
            {initials(name)}
          </span>
        </button>
      </p>
    );
  }

  return (
    <p className="flex items-center text-sm">
      {/* The button alone: why sign-in exists is the landing's line to say. */}
      <span ref={buttonSlot} />
    </p>
  );
}
