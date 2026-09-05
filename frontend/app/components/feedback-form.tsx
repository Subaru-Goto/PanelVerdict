"use client";

import { useState } from "react";

import { sendFeedback } from "../lib/api";

/** One box at the foot of a live report (053/#150, decisions Q2 and Q5):
 *  the reader says what was unclear or wrong, in their own words. Feedback is
 *  stored against the test and read by a person, not answered — the line
 *  after Send says so. A failed send keeps the text in the box. */
export default function FeedbackForm({ testId }: { testId: string }) {
  const [draft, setDraft] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">(
    "idle",
  );

  if (state === "sent") {
    return (
      <p className="text-sm text-ink-2">
        Thanks. Feedback is read, not replied to.
      </p>
    );
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        setState("sending");
        sendFeedback(testId, draft.trim()).then(
          () => setState("sent"),
          () => setState("failed"),
        );
      }}
    >
      <label htmlFor="feedback-body" className="text-sm font-medium">
        Something unclear or wrong here? Tell us.
      </label>
      <textarea
        id="feedback-body"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        disabled={state === "sending"}
        rows={3}
        maxLength={2000}
        className="rounded border border-line px-3 py-2 text-sm"
      />
      {state === "failed" && (
        <p role="alert" className="text-sm text-ink-2">
          Could not send. Your message is still here, try again.
        </p>
      )}
      <button
        type="submit"
        disabled={state === "sending" || draft.trim() === ""}
        className="self-start rounded bg-ink px-3 py-2 text-sm font-medium text-surface disabled:bg-surface-2 disabled:text-ink-3"
      >
        Send feedback
      </button>
    </form>
  );
}
