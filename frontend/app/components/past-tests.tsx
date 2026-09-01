"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import Link from "next/link";

import {
  forgetTest,
  myTests,
  onRunsChanged,
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
 * A row is a link to the wizard, which fetches the stored report and hands it
 * to its own `done` phase (119/#257): a stored report *is* the report, so a
 * second render path for it would be a second place to draw it wrongly — and a
 * link works from any page the rail shows on, not only the wizard.
 */
export default function PastTests() {
  // null until the session is known, so a rail does not flash at a visitor who
  // turns out to be signed in — the reason `sign-in.tsx` starts here too.
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [tests, setTests] = useState<StoredTest[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  // The row whose × has been clicked once. Deleting asks first, inline —
  // ChatGPT's and Gemini's rails both put a confirmation between the click
  // and the delete (085/#176, decided 2026-09-01) — and the question is
  // withdrawn when the pointer leaves the row or on Escape, so it can never
  // sit armed under the next unsuspecting click.
  const [confirming, setConfirming] = useState<string | null>(null);
  /** What failed, not just whether: the banner is shared between the first
   *  read and a page append, and their remedies differ — retrying a failed
   *  "Show more" with a full reload would throw away every page reached.
   *  `cursor` is what the failed read was fetching; null means page one. */
  const [failed, setFailed] = useState<{ cursor: string | null } | null>(null);
  const [reading, setReading] = useState(false);
  const [fetchingMore, setFetchingMore] = useState(false);

  // Counts session notifications, so a refetch happens even when `signedIn`
  // comes back the same value for a different account. Mirrored in a ref so an
  // in-flight "Show more" can tell its session ended while it was away.
  const [session, setSession] = useState(0);
  const sessionRef = useRef(0);

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
        setNextCursor(null);
        setFailed(null);
        setQuery("");
        sessionRef.current += 1;
        setSession((count) => count + 1);
      }),
    [],
  );

  // Replaces, never appends — after a finished run or a session change the
  // rail deliberately holds the newest page again: the event that fired it
  // put the newest row there, and stitching old pages onto a list that just
  // changed underneath them could repeat or skip a row.
  // Counts reads the way `session` counts sessions: two firsts can be away at
  // once (a retry racing the run-finished refresh), and only the latest one
  // started may speak — a superseded success would stamp older rows over
  // newer ones, and a superseded failure would raise "could not be loaded"
  // over rows that loaded fine. The session is re-checked too: Supabase can
  // collapse a sign-out and sign-in to true→true, so this component never
  // unmounts, and a read begun under the old account must say nothing.
  const readRef = useRef(0);

  const load = useCallback(() => {
    if (signedIn !== true) return;
    const read = ++readRef.current;
    const asked = sessionRef.current;
    setReading(true);
    const current = () =>
      read === readRef.current && asked === sessionRef.current;
    myTests().then(
      (page) => {
        if (!current()) return;
        setTests(page.tests);
        setNextCursor(page.next_cursor);
        // Cleared on success, or one cold start leaves "could not be loaded"
        // standing above the rows that then arrive — and permanently suppresses
        // the empty state, which is gated on it (117/#252, review).
        setFailed(null);
        setReading(false);
      },
      () => {
        if (!current()) return;
        setFailed({ cursor: null });
        setReading(false);
      },
    );
  }, [signedIn]);

  // The page below the rows already shown. An append, so two rules `load`
  // does not need: a page fetched under a session that ended while it was in
  // flight is dropped — the same not-this-account's-headlines rule the
  // listener's clearing enforces for the first read (117/#252, review) — and
  // only one fetch is ever away, or a double-click would append the same page
  // twice. The banner clears on success for `load`'s own documented reason.
  async function loadNextPage(cursor: string): Promise<void> {
    if (fetchingMore) return;
    setFetchingMore(true);
    const asked = sessionRef.current;
    // An append onto a list a fresh first read just replaced would gap or
    // repeat rows — the read counter says the list it belongs to is gone.
    const read = readRef.current;
    try {
      const page = await myTests(cursor);
      if (sessionRef.current !== asked || readRef.current !== read) return;
      setTests((current) => [...(current ?? []), ...page.tests]);
      setNextCursor(page.next_cursor);
      setFailed(null);
    } catch {
      if (sessionRef.current === asked && readRef.current === read)
        setFailed({ cursor });
    } finally {
      setFetchingMore(false);
    }
  }

  // On mount, and again whenever the session is announced — `session` is in the
  // dependencies for that second reason, since `signedIn` can come back the
  // same value for a different account.
  useEffect(load, [load, session]);
  // A finished run is a new row. `onRunsChanged` already fires exactly then —
  // it is what keeps the remaining-runs figure honest — so the rail reuses it
  // rather than polling.
  useEffect(() => onRunsChanged(load), [load]);

  if (signedIn !== true) return null;

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

      {failed !== null && (
        <p className="text-sm text-ink-2">
          Your past tests could not be loaded. They are not lost —{" "}
          {/* One click, not a reload: the likely failure on this deploy is a
              cold backend (docs/deploy.md), and a reload loses the page. It
              retries the read that failed — a page append keeps its pages —
              and goes quiet while the read is away, which can be a minute. */}
          <button
            type="button"
            disabled={reading || fetchingMore}
            onClick={() =>
              failed.cursor === null ? load() : void loadNextPage(failed.cursor)
            }
            className="cursor-pointer underline underline-offset-2 disabled:cursor-default disabled:text-ink-3 disabled:no-underline"
          >
            try again
          </button>
          .
        </p>
      )}

      {tests !== null && tests.length === 0 && failed === null && (
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
              <li
                className="flex items-start gap-2"
                key={test.test_id}
                onMouseLeave={() =>
                  setConfirming((armed) =>
                    armed === test.test_id ? null : armed,
                  )
                }
              >
                <Link
                  className="flex-1 text-left text-sm hover:underline"
                  href={`/test?open=${test.test_id}`}
                >
                  <span className="block">
                    “{test.variants.a}” vs “{test.variants.b}”
                  </span>
                  <span className="block text-ink-2">
                    {railSummary(test.verdict)}
                  </span>
                </Link>
                {confirming === test.test_id ? (
                  <button
                    aria-label={`Really delete the test of “${test.variants.a}”?`}
                    className="text-sm font-medium text-red"
                    onClick={() => {
                      setConfirming(null);
                      void forget(test.test_id);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") setConfirming(null);
                    }}
                    type="button"
                  >
                    Delete?
                  </button>
                ) : (
                  <button
                    aria-label={`Delete the test of “${test.variants.a}”`}
                    className="text-ink-2 hover:text-ink"
                    onClick={() => setConfirming(test.test_id)}
                    type="button"
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
          {shown.length === 0 && (
            <p className="text-sm text-ink-2">
              {/* The search reads the rows on hand; a flat "no test matches"
                  while unsearched pages remain would be a false sentence about
                  the reader's own history. */}
              {nextCursor === null
                ? `No test matches “${query}”.`
                : `No test loaded so far matches “${query}” — Show more reaches
                   further back.`}
            </p>
          )}
          {nextCursor !== null && (
            <button
              className="self-start text-sm text-ink-2 hover:text-ink hover:underline"
              disabled={fetchingMore}
              onClick={() => void loadNextPage(nextCursor)}
              type="button"
            >
              Show more
            </button>
          )}
        </>
      )}
    </section>
  );
}
