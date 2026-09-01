"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { LANDING_DISCLOSURE } from "../lib/disclosure";
import { onAuthChange, signInAvailable } from "../lib/auth";
import SignInSheet from "./sign-in-sheet";

const PRINCIPLES: { title: string; body: string }[] = [
  {
    title: "Every vote is on the record",
    body: "Each panel member votes and says why, in their own words. The reasons are in the report, not behind a summary.",
  },
  {
    title: "Uncertainty stays attached",
    body: "The verdict carries the range the true preference could plausibly sit in, and says plainly when the gap is too small to call.",
  },
  {
    title: "You approve the panel",
    body: "The votes are the cost of a run, and none is cast until you have seen how your audience was read and confirmed it. Reading the audience itself costs a little.",
  },
];

/** The public face (119/#257): hero, one CTA, the three principles, the
 *  disclosure. The CTA swaps with sign-in state — signed out the form does not
 *  exist (prototype, 2026-08-25), and until the demo replay ships (#156) the
 *  only honest offer is signing in, so that is what the button says.
 */
export default function Landing() {
  // null until the session is known — the CTA must not flash "sign in" at a
  // reader who turns out to be signed in (the reason sign-in.tsx starts here).
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const available = signInAvailable();

  useEffect(
    () =>
      onAuthChange((value) => {
        setSignedIn(value);
        // Signing in closes the sheet from wherever it was opened.
        if (value) setSheetOpen(false);
      }),
    [],
  );

  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-16 px-6 py-16">
      <div className="flex flex-col items-center gap-5 text-center">
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-ink-2">
          Synthetic A/B testing
        </p>
        <h1>A verdict — and how sure it is.</h1>
        <p className="max-w-xl text-ink-2">
          A panel of synthetic readers judges both versions of your copy and
          reports which one it prefers, how wide the lead is, and when the lead
          is too small to call.
        </p>
        {signedIn === true ? (
          <>
            <Link
              href="/test"
              className="rounded-pill bg-ink px-6 py-3 font-medium text-surface"
            >
              Run your own test
            </Link>
            <p className="text-xs text-ink-3">Three runs a day.</p>
          </>
        ) : signedIn === false ? (
          <>
            {/* 061: the demo is the one runnable thing signed out, so it is
                the primary — a real captured run, replayed, needing no
                account. Sign-in becomes the second line. */}
            <Link
              href="/test?demo=save-half"
              className="rounded-pill bg-ink px-6 py-3 font-medium text-surface"
            >
              Run the demo test
            </Link>
            <p className="text-xs text-ink-3">
              A real panel&rsquo;s run, replayed — nothing spent.{" "}
              {available && (
                <button
                  type="button"
                  onClick={() => setSheetOpen(true)}
                  className="underline underline-offset-2"
                >
                  Sign in to run your own — three runs a day.
                </button>
              )}
            </p>
          </>
        ) : null}
        <p className="max-w-xl text-sm text-ink-3">{LANDING_DISCLOSURE}</p>
      </div>
      <div className="grid gap-10 border-t border-line pt-10 sm:grid-cols-3">
        {PRINCIPLES.map(({ title, body }) => (
          <div
            key={title}
            className="flex flex-col gap-2 border-t-2 border-ink pt-4"
          >
            <h3>{title}</h3>
            <p className="text-sm text-ink-2">{body}</p>
          </div>
        ))}
      </div>
      {sheetOpen && <SignInSheet onClose={() => setSheetOpen(false)} />}
    </section>
  );
}
