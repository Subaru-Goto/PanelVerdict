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

  useEffect(() => onAuthChange(setSignedIn), []);

  const load = useCallback(() => {
    if (signedIn !== true) return;
    myTests().then(setTests, () => setFailed(true));
  }, [signedIn]);

  useEffect(load, [load]);
  // A finished run is a new row. `onRunsChanged` already fires exactly then —
  // it is what keeps the remaining-runs figure honest — so the rail reuses it
  // rather than polling.
  useEffect(() => onRunsChanged(load), [load]);

  if (signedIn !== true) return null;

  async function open(testId: string): Promise<void> {
    try {
      onOpen(await myTest(testId));
    } catch {
      // The row is stale — most likely deleted in another tab. Reloading the
      // rail is both the recovery and the explanation.
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
            <p className="text-sm text-ink-2">
              No test matches “{query}”.
            </p>
          )}
        </>
      )}
    </section>
  );
}
