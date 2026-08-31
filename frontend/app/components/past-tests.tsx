"use client";

import { useCallback, useEffect, useState } from "react";

import {
  forgetTest,
  myTest,
  myTests,
  onRunsChanged,
  type EvaluateResponse,
  type StoredTest,
} from "../lib/api";
import { onAuthChange } from "../lib/auth";
import { railSummary } from "../lib/verdict";

/** The signed-in account's own tests (117/#252).
 *
 * Signed out this renders nothing at all — not an empty rail and not a prompt.
 * The tests are the account's, so a rail for a visitor with no account would be
 * a permanently empty box explaining itself.
 *
 * Reopening hands the stored report to the page's existing `done` phase rather
 * than rendering it here: a stored report *is* the report, so a second render
 * path for it would be a second place to draw it wrongly.
 */
export default function PastTests({
  onOpen,
}: {
  onOpen: (result: EvaluateResponse) => void;
}) {
  // null until the session is known, so a rail does not flash at a visitor who
  // turns out to be signed in — the reason `sign-in.tsx` starts here too.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [tests, setTests] = useState<StoredTest[] | null>(null);
  const [query, setQuery] = useState("");
  const [failed, setFailed] = useState(false);

  // Counts session notifications, so a refetch happens even when `signedIn`
  // comes back the same value for a different account.
  const [session, setSession] = useState(0);

  useEffect(
    () =>
      onAuthChange((value) => {
        setSignedIn(value);
        // Cleared here rather than in an effect watching `signedIn`: this is
        // the moment the session changed, and the boolean cannot represent it —
        // two accounts both report `true`, and a sign-out and sign-in landing
        // in one batch collapse to no change at all. Without this the new
        // session shows the previous account's headlines until its own fetch
        // resolves, and a click on one 404s (117/#252, review).
        setTests(null);
        setFailed(false);
        setQuery("");
        setSession((count) => count + 1);
      }),
    [],
  );

  const load = useCallback(() => {
    if (signedIn !== true) return;
    myTests().then(
      (loaded) => {
        setTests(loaded);
        // Cleared on success, or one cold start leaves "could not be loaded"
        // standing above the rows that then arrive — and permanently suppresses
        // the empty state, which is gated on it (117/#252, review).
        setFailed(false);
      },
      () => setFailed(true),
    );
  }, [signedIn]);

  // On mount, and again whenever the session is announced — `session` is in the
  // dependencies for that second reason, since `signedIn` can come back the
  // same value for a different account.
  useEffect(load, [load, session]);
  // A finished run is a new row. `onRunsChanged` already fires exactly then —
  // it is what keeps the remaining-runs figure honest — so the rail reuses it
  // rather than polling.
  useEffect(() => onRunsChanged(load), [load]);

  if (signedIn !== true) return null;

  async function open(testId: string): Promise<void> {
    try {
      onOpen(await myTest(testId));
    } catch (error) {
      // A 404 means the row is stale — deleted in another tab — and reloading
      // the rail is both the recovery and the explanation. Anything else and
      // the row is still there, so a silent reload would look like the click
      // did nothing (117/#252, review).
      const stale = error instanceof Error && /404/.test(error.message);
      if (!stale) setFailed(true);
      load();
    }
  }

  async function forget(testId: string): Promise<void> {
    // Removed here first: the delete is idempotent and a 404 is not an error,
    // so the row never needs to come back, and a rail that waits for the round
    // trip feels broken on a slow connection.
    setTests((current) =>
      (current ?? []).filter((test) => test.test_id !== testId),
    );
    await forgetTest(testId).catch(() => load());
  }

  const term = query.trim().toLowerCase();
  // Searched on the headlines, which is what the rows show — searching fields a
  // reader cannot see would make a row vanish for no visible reason.
  const shown = (tests ?? []).filter((test) =>
    Object.values(test.variants).join(" ").toLowerCase().includes(term),
  );

  return (
    <section aria-label="Your tests" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-ink-2">Your tests</h2>

      {failed && (
        <p className="text-sm text-ink-2">
          Your past tests could not be loaded. They are not lost — reload to try
          again.
        </p>
      )}

      {tests !== null && tests.length === 0 && !failed && (
        <p className="text-sm text-ink-2">
          Nothing yet. A test you run is kept here.
        </p>
      )}

      {tests !== null && tests.length > 0 && (
        <>
          <input
            aria-label="Search your tests"
            className="rounded border border-line px-2 py-1 text-sm"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search your tests"
            value={query}
          />
          <ul className="flex flex-col gap-2">
            {shown.map((test) => (
              <li className="flex items-start gap-2" key={test.test_id}>
                <button
                  className="flex-1 text-left text-sm hover:underline"
                  onClick={() => void open(test.test_id)}
                  type="button"
                >
                  <span className="block">
                    “{test.variants.a}” vs “{test.variants.b}”
                  </span>
                  <span className="block text-ink-2">
                    {railSummary(test.verdict)}
                  </span>
                </button>
                <button
                  aria-label={`Delete the test of “${test.variants.a}”`}
                  className="text-ink-2 hover:text-ink"
                  onClick={() => void forget(test.test_id)}
                  type="button"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          {shown.length === 0 && (
            <p className="text-sm text-ink-2">No test matches “{query}”.</p>
          )}
        </>
      )}
    </section>
  );
}
