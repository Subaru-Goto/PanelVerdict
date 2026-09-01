"use client";

import { useEffect, useRef, useState } from "react";

import {
  displayName,
  mountGoogleButton,
  onAuthChange,
  signInAvailable,
  signOut,
} from "../lib/auth";

/** Signing in and out, as the prototype's nav settles it (063/#158, 092/#197,
 * amended 2026-09-01): signed out, Google's own button; signed in, the "who"
 * pill — the reader's name with an initials disc — whose click opens a
 * one-item menu, and the item is the sign-out. The remaining-runs count lives
 * beside the run button (`Allowance`), where spending happens, not here.
 * Never appears in a build that cannot sign anyone in.
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
  const [menuOpen, setMenuOpen] = useState(false);
  const buttonSlot = useRef<HTMLSpanElement | null>(null);
  const wrapper = useRef<HTMLDivElement | null>(null);
  const pill = useRef<HTMLButtonElement | null>(null);
  const available = signInAvailable();

  useEffect(
    () =>
      onAuthChange((value) => {
        setSignedIn(value);
        // Cleared on the way out, not at the click: the pill must stay up as
        // sign-out's feedback until the session event lands — and a cleared
        // name here cannot flash into the next session's pill. The menu goes
        // with it, or it would reopen itself on the next sign-in.
        if (!value) {
          setName(null);
          setMenuOpen(false);
        }
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

  // Light dismiss by listening, not by covering: a scrim over the page
  // swallowed the first click on every other control (and hit-tested above
  // the pill itself, so its own toggle never ran in a real browser). Escape
  // works from anywhere and hands focus back to the pill, so a keyboard
  // reader is never stranded in an open menu.
  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      pill.current?.focus();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  // A build with no Supabase project — local development, CI — renders as it
  // did before this existed. A button that cannot work is worse than none.
  // Same for the moment before the session is known: nothing, rather than a
  // guess that has to be taken back. And the same again for the moment before
  // the name is known: a pill with a blank disc reads as broken, not loading.
  if (!available || signedIn === null) return null;

  if (signedIn) {
    if (name === null) return null;
    return (
      // The pill opens a one-item menu rather than signing out itself
      // (amended 2026-09-01): an accidental click on an unlabeled control
      // must not end the session — the sign-out is the menu's deliberate
      // second click. A disclosure, not an ARIA menu: role="menu" announces
      // a keyboard contract (arrow focus, typeahead) one button doesn't need.
      <div ref={wrapper} className="relative flex items-center text-sm">
        <button
          ref={pill}
          type="button"
          aria-label={`Account: ${name}`}
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen((open) => !open)}
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
        {menuOpen && (
          <div className="absolute right-0 top-full z-50 mt-2 min-w-36 rounded border border-line bg-surface p-1">
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                void signOut();
              }}
              className="w-full cursor-pointer rounded px-3 py-2 text-left text-[13px] hover:bg-surface-2"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <p className="flex items-center text-sm">
      {/* The button alone: why sign-in exists is the landing's line to say. */}
      <span ref={buttonSlot} />
    </p>
  );
}
