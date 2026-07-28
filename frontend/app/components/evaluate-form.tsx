"use client";

import { useState, type SubmitEvent } from "react";

import { useEvaluate } from "../lib/use-evaluate";
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

export default function EvaluateForm() {
  const [targetDescription, setTargetDescription] = useState("");
  const [headlineA, setHeadlineA] = useState("");
  const [headlineB, setHeadlineB] = useState("");
  const { state, submit } = useEvaluate();

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit({ targetDescription, headlineA, headlineB });
  }

  const disabled =
    !targetDescription.trim() ||
    !headlineA.trim() ||
    !headlineB.trim() ||
    state.phase === "loading";

  return (
    <div className="flex flex-col gap-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <Field
          label="Who should judge these?"
          value={targetDescription}
          onChange={setTargetDescription}
          placeholder="Japanese homeowners in their 40s who research before buying"
          multiline
        />
        <Field
          label="Headline A"
          value={headlineA}
          onChange={setHeadlineA}
          placeholder="Save 50% today"
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
      </form>

      {state.phase === "error" && (
        <p className="text-red-600">Error: {state.message}</p>
      )}

      {state.phase === "done" && <Report result={state.result} />}
    </div>
  );
}
