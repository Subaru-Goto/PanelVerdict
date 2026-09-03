"use client";

import { unstable_catchError } from "next/error";

/** Two error boundaries for the report view (049/#147), nested: the analyst
 *  dock renders inside the report, and a chat bug must not take the paid
 *  verdict off the screen with it.
 *
 *  Component-level rather than a route `error.tsx`, which would replace the
 *  whole page — form, "Test again" and all — for a crash in one subtree.
 *  The fallback says one sentence and offers one action; the error's own
 *  words go to the console, never to the reader. `onRefresh` refetches the
 *  stored test and redraws it (035/#136 made every report on screen
 *  reopenable) — a re-render of the same data would only crash again. */

type RefreshProps = { onRefresh: () => void };

const REFRESH_LABEL = "Refresh";

function fallbackFor(sentence: string) {
  // The second argument (the error, retry, reset) is deliberately unused:
  // retrying the same data would crash again, and the error's words are not
  // for the reader — React has already logged them.
  return function Fallback({ onRefresh }: RefreshProps) {
    return (
      <div
        role="alert"
        className="flex flex-col gap-3 rounded border border-line p-4 text-sm"
      >
        <p>{sentence}</p>
        <button
          type="button"
          onClick={onRefresh}
          className="self-start rounded border border-line px-3 py-1.5 text-sm"
        >
          {REFRESH_LABEL}
        </button>
      </div>
    );
  };
}

export const REPORT_CRASH_SENTENCE =
  "Something went wrong drawing this report. Refresh to load it again.";
export const ANALYST_CRASH_SENTENCE =
  "The analyst is unavailable right now. Refresh to try again.";

export const ReportBoundary = unstable_catchError(
  fallbackFor(REPORT_CRASH_SENTENCE),
);
export const AnalystBoundary = unstable_catchError(
  fallbackFor(ANALYST_CRASH_SENTENCE),
);
