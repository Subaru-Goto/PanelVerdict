"use client";

import { useEffect, useRef, useState } from "react";

import {
  readerTurns,
  type Analyst,
  type AnalystTurn,
} from "../lib/use-analyst";

/** The final chip copy. Each maps to a tool the demo has to
 *  show — the first two to analyze_results, the third to search_personas.
 *  Deliberately no chip triggers run_panel_test: a new panel run spends real
 *  money, so that ask must be typed, never one accidental click away. */
/** PENDING USER SIGN-OFF (not yet approved): how close to the bottom still
 *  counts as "following along". A feel parameter, judged in a browser. */
const PINNED_SLACK_PX = 48;

const CHIPS = [
  "Why did the test stop early?",
  "How sure are we about the winner?",
  "Who was on this panel?",
];

function Turn({ turn }: { turn: AnalystTurn }) {
  if (turn.role === "user") {
    return (
      <p className="ml-8 self-end rounded-lg bg-zinc-100 px-3 py-2 text-sm dark:bg-zinc-800">
        {turn.text}
      </p>
    );
  }
  return (
    <div className="mr-8 flex flex-col gap-1 self-start">
      {turn.text !== "" && (
        <p className="whitespace-pre-wrap rounded-lg border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-700">
          {turn.text}
        </p>
      )}
      {turn.status !== null && (
        <p className="px-1 text-xs italic text-zinc-500">{turn.status}</p>
      )}
      {turn.error !== null && (
        <p className="rounded-lg border border-red-300 px-3 py-2 text-sm text-red-700 dark:border-red-700 dark:text-red-400">
          {turn.error}
        </p>
      )}
    </div>
  );
}

export default function AnalystDock({ analyst }: { analyst: Analyst }) {
  // Closed on a fresh report now. Variant C traded an open dock for the chips
  // being visible once, but the report already carries the analyst's opening
  // summary — an open dock would only print it a second time.
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const { turns, busy, send } = analyst;
  // The report's opening exchange is on the page already; the dock shows the
  // conversation the reader is having. Both the transcript and the chips read
  // this, so they cannot disagree about whether one has started.
  const visible = readerTurns(turns);

  const listRef = useRef<HTMLDivElement | null>(null);
  // Follow the conversation only while the reader is near the bottom, so
  // scrolling up to reread is not fought by the typewriter. jsdom does no
  // layout, so nothing here is unit-testable — verified in a browser.
  const pinnedRef = useRef(true);

  useEffect(() => {
    const list = listRef.current;
    if (list && pinnedRef.current) list.scrollTop = list.scrollHeight;
  }, [turns]);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 rounded-full bg-zinc-900 px-5 py-3 text-sm font-medium text-white shadow-lg dark:bg-zinc-100 dark:text-zinc-900"
      >
        Ask the analyst
      </button>
    );
  }

  return (
    <section
      aria-label="Analyst chat"
      className="fixed bottom-6 right-6 flex max-h-[70vh] w-96 max-w-[calc(100vw-3rem)] flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-xl dark:border-zinc-700 dark:bg-zinc-900"
    >
      <header className="flex items-start justify-between gap-2">
        <div className="flex flex-col">
          <h2 className="text-sm font-semibold">Ask the analyst</h2>
          <p className="text-xs text-zinc-500">
            Answers come from this test&apos;s own numbers. Every panelist is
            synthetic.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
        >
          Close
        </button>
      </header>

      {visible.length > 0 && (
        <div
          ref={listRef}
          onScroll={() => {
            const list = listRef.current;
            if (list) {
              pinnedRef.current =
                list.scrollHeight - list.scrollTop - list.clientHeight <
                PINNED_SLACK_PX;
            }
          }}
          className="flex flex-col gap-2 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {visible.map((turn, index) => (
            <Turn key={index} turn={turn} />
          ))}
        </div>
      )}

      {visible.length === 0 && (
        <div className="flex flex-wrap gap-2">
          {CHIPS.map((chip) => (
            <button
              key={chip}
              type="button"
              disabled={busy}
              onClick={() => void send(chip)}
              className="rounded-full border border-zinc-300 px-3 py-1.5 text-xs hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800"
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
          setDraft("");
        }}
      >
        <input
          aria-label="Ask about this test"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          disabled={busy}
          placeholder="Ask about this test…"
          className="min-w-0 flex-1 rounded border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
        />
        <button
          type="submit"
          disabled={busy || draft.trim() === ""}
          className="rounded bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          Send
        </button>
      </form>
    </section>
  );
}
