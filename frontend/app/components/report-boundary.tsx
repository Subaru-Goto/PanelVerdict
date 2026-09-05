"use client";

import { unstable_catchError } from "next/error";

/** The report view's error boundaries (049/#147): one around the report, one
 *  around the analyst inside it, so a chat bug leaves the paid verdict on
 *  screen. Component-level, not a route `error.tsx`, which would replace the
 *  whole page. The card says one sentence and offers one action; the error
 *  itself is React's to log. */

type CardProps = {
  onRefresh: () => void;
  /** A refresh already in flight: the button waits, because each redraw
   *  opens a paid analyst turn. */
  refreshing?: boolean;
};

function cardFor(sentence: string) {
  return function Card({ onRefresh, refreshing = false }: CardProps) {
    return (
      <div
        role="alert"
        className="flex flex-col gap-3 rounded border border-line p-4 text-sm"
      >
        <p>{sentence}</p>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="self-start rounded border border-line px-3 py-1.5 text-sm disabled:opacity-50"
        >
          Refresh
        </button>
      </div>
    );
  };
}

export const ReportBoundary = unstable_catchError(
  cardFor(
    "Something went wrong drawing this report. Refresh to load it again.",
  ),
);
export const AnalystBoundary = unstable_catchError(
  cardFor("The analyst is unavailable right now. Refresh to try again."),
);

/** The feedback box's own boundary (053/#150): a sibling of the analyst, so a
 *  bug in it cannot blank the verdict. One sentence, no action — there is
 *  nothing to refresh, and the report is not what broke. */
export const FeedbackBoundary = unstable_catchError(
  function FeedbackFallback() {
    return (
      <p role="alert" className="text-sm text-ink-2">
        The feedback box is unavailable right now. The report is unaffected.
      </p>
    );
  },
);
