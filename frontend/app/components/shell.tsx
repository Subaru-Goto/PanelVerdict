"use client";

import Link from "next/link";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { onAuthChange } from "../lib/auth";
import PastTests from "./past-tests";
import SignIn from "./sign-in";

/** How the wizard tells the frame it is holding at the gate. A context rather
 *  than a prop: the gate is the wizard's phase, and the frame is its ancestor.
 */
const GateContext = createContext<(open: boolean) => void>(() => {});

/** Signal from the page that the panel gate is open. The gate is a decision
 *  about spending money, and the rail beside it is an invitation to leave it
 *  half-answered (#252) — so the frame puts the rail away while this is true.
 */
export function useGateSignal(open: boolean): void {
  const signal = useContext(GateContext);
  useEffect(() => {
    signal(open);
    // A page that unmounts mid-gate must not leave the rail hidden forever.
    return () => signal(false);
  }, [open, signal]);
}

/** The three demo pairs, verbatim from the prototype. Rows, not buttons: a
 *  control that runs the demo is #156's to add. */
const SAMPLES: { pair: string; verdict: string }[] = [
  {
    pair: "“Save 50% this week” vs “Members save half price this week”",
    verdict: "71% preferred the first",
  },
  {
    pair: "“Book in 30 seconds” vs “Reserve your slot now”",
    verdict: "too close to call",
  },
  {
    pair: "“Built for teams” vs “Built for teams like yours”",
    verdict: "66% preferred the second",
  },
];

/** The frame every page sits in (119/#257): a header carrying identity and
 *  account — no tabs, the product has one function — and the rail.
 *
 *  Signed out the rail is a demo shelf: the same samples for everyone, static
 *  copy until #156 makes them run. Signed in it is yours: new test + saved
 *  tests, samples gone.
 */
export default function Shell({ children }: { children: ReactNode }) {
  // null until the session is known, so the demo shelf does not flash at a
  // reader who turns out to be signed in.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [railAway, setRailAway] = useState(false);
  const [gateOpen, setGateOpen] = useState(false);

  useEffect(() => onAuthChange(setSignedIn), []);

  return (
    <div className="flex flex-1 flex-col">
      <nav className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="flex items-center gap-3">
          <button
            type="button"
            aria-label="Show or hide the rail"
            onClick={() => setRailAway((away) => !away)}
            className="p-1"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <Link
            href="/"
            className="text-[13px] font-bold uppercase tracking-[0.32em]"
          >
            Panelverdict
          </Link>
        </div>
        <SignIn />
      </nav>
      <div className="flex flex-1">
        <aside
          aria-label="Your tests and sample verdicts"
          hidden={railAway || gateOpen}
          className="w-64 shrink-0 border-r border-line px-4 py-5"
        >
          {signedIn === true && (
            <div className="flex flex-col gap-4">
              <Link
                href="/test"
                className="rounded-pill border border-ink px-4 py-2 text-center text-sm font-medium"
              >
                New test
              </Link>
              <PastTests />
            </div>
          )}
          {signedIn === false && (
            <div className="flex flex-col gap-3">
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-ink-3">
                Sample verdicts
              </p>
              {SAMPLES.map(({ pair, verdict }) => (
                <p key={pair} className="flex flex-col gap-0.5 text-sm">
                  <span>{pair}</span>
                  <span className="text-xs text-ink-3">{verdict}</span>
                </p>
              ))}
            </div>
          )}
        </aside>
        <main className="min-w-0 flex-1">
          <GateContext.Provider value={setGateOpen}>
            {children}
          </GateContext.Provider>
        </main>
      </div>
    </div>
  );
}
