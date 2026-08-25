"use client";

import { useEffect, useState, type SubmitEvent } from "react";

import { useEvaluate } from "../lib/use-evaluate";
import PanelGate from "./panel-gate";
import Report from "./report";

const INPUT_CLASS =
  "rounded border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900";

function Field({
  label,
  value,
  onChange,
  placeholder,
  multiline = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  multiline?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={2}
          className={INPUT_CLASS}
        />
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={INPUT_CLASS}
        />
      )}
    </label>
  );
}

/** Proof that a run is alive, not frozen.
 *
 *  A disabled button looks identical whether the panel is voting or the
 *  request died, which is exactly how a slow run gets read as a broken one. A
 *  number that keeps moving settles it, and it costs the backend nothing — no
 *  streaming, no progress endpoint, no estimate that could be wrong.
 *
 *  Deliberately not a percentage: nothing here knows how far along the run is,
 *  and a bar that guesses would be a worse lie than no bar at all. */
function Waiting() {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <p
      role="status"
      className="flex items-center gap-2 text-sm text-zinc-500"
      aria-live="polite"
    >
      <span
        aria-hidden
        className="h-2 w-2 animate-pulse rounded-full bg-zinc-500"
      />
      Each panelist is reading both headlines and picking one — {seconds}s so
      far.
    </p>
  );
}

export default function EvaluateForm({
  // Passed in from the server-rendered page rather than fetched here, so the
  // line is in the first paint. A disclosure arriving after hydration leaves a
  // window in which someone has already typed.
  tracing = false,
}: {
  tracing?: boolean;
}) {
  const [targetDescription, setTargetDescription] = useState("");
  const [headlineA, setHeadlineA] = useState("");
  const [headlineB, setHeadlineB] = useState("");
  const { state, submit, answerGate, reset } = useEvaluate();

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit({ targetDescription, headlineA, headlineB });
  }

  // The audience is deliberately absent: two headlines against a cross-section
  // of the whole pool is a real test, and blank is a choice rather than an
  // omission. The backend skips the translator entirely when it is empty.
  const disabled =
    !headlineA.trim() || !headlineB.trim() || state.phase === "loading";

  // Once a report exists the page stops being a form: the reader wants the
  // answer at the top rather than the inputs they already filled in.
  if (state.phase === "done") {
    return (
      <div className="flex flex-col gap-6">
        <button
          type="button"
          onClick={reset}
          className="self-start rounded border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700"
        >
          Test again
        </button>
        <Report result={state.result} />
      </div>
    );
  }

  // Holding at the gate: the reader decides whether to buy the votes.
  if (state.phase === "gated") {
    return (
      <PanelGate
        preview={state.preview}
        onAccept={() => void answerGate("accept")}
        onBack={reset}
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <Field
          label="Who should judge these? (optional)"
          value={targetDescription}
          onChange={setTargetDescription}
          placeholder="Japanese males in their 30s"
          multiline
        />
        <Field
          label="Headline A"
          value={headlineA}
          onChange={setHeadlineA}
          placeholder="Save 50% this week"
        />
        <Field
          label="Headline B"
          value={headlineB}
          onChange={setHeadlineB}
          placeholder="Members save half price this week"
        />
        <button
          type="submit"
          disabled={disabled}
          className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {state.phase === "loading" ? "Asking the panel…" : "Evaluate"}
        </button>
        {/* Submitting counts as interacting with an AI system, so the
            disclosure sits with the submit control rather than in a footer —
            told before the exchange, where the telling can still change it. */}
        <p className="text-xs text-zinc-500">
          PanelVerdict is an AI system: the panel is synthetic personas, and the
          verdict and analyst answers are AI-generated.
        </p>
        {/* Only when this deployment is really tracing — the backend's own
            answer, not a second flag here that could disagree with it. A
            deterrent, not a control: the controls are the screener and the
            limits. */}
        {tracing && (
          <p className="text-xs text-zinc-500">
            Runs are traced for debugging: what you type — your audience,
            both headlines, and anything you later ask the analyst — is sent to
            LangSmith, outside our infrastructure. Don&rsquo;t paste anything
            unreleased.
          </p>
        )}
      </form>

      {state.phase === "loading" && <Waiting />}

      {state.phase === "error" && (
        <p className="text-red-600">Error: {state.message}</p>
      )}
    </div>
  );
}
