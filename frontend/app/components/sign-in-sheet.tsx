"use client";

import { useEffect, useRef } from "react";

import { mountGoogleButton } from "../lib/auth";

/** The sign-in sheet from the prototype: the provider's own button and the
 *  reason it is asked for, in a dialog. Signing in happens here, no redirect.
 */
export default function SignInSheet({ onClose }: { onClose: () => void }) {
  const buttonSlot = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (buttonSlot.current === null) return;
    // Google renders its own button into the slot; an unavailable identity
    // provider leaves it empty rather than throwing into React.
    void mountGoogleButton(buttonSlot.current).catch(() => {});
  }, []);

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-ink/40 p-6"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label="Sign in"
        className="flex w-full max-w-md flex-col gap-4 bg-surface p-8"
        onClick={(e) => e.stopPropagation()}
      >
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-ink-2">
          One step
        </p>
        <h2>Sign in to run your own test.</h2>
        <p className="text-sm text-ink-2">
          A test of your own spends money, so it is counted to a person rather
          than to a network address. A signed-in account gets three runs a day.
          Signing in happens on this page, with no redirect.
        </p>
        <div ref={buttonSlot} />
        <p className="text-xs text-ink-3">
          Google tells us your name, email address and profile picture. Verdicts
          are stored against an internal id, not your email. Nothing is posted
          anywhere on your behalf.
        </p>
        <button
          type="button"
          onClick={onClose}
          className="self-start text-sm underline underline-offset-2"
        >
          Not now
        </button>
      </div>
    </div>
  );
}
