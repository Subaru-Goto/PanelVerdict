"use client";

import { useState, type FormEvent } from "react";

import { evaluate, type EvaluateResponse } from "../lib/api";

export default function EvaluateForm() {
  const [headlineA, setHeadlineA] = useState("");
  const [headlineB, setHeadlineB] = useState("");
  const [result, setResult] = useState<EvaluateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await evaluate(headlineA, headlineB));
    } catch (err) {
      if (err instanceof Error) setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const disabled = !headlineA.trim() || !headlineB.trim() || loading;
  const inputClass =
    "rounded border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900";

  return (
    <div className="flex flex-col gap-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          Headline A
          <input
            value={headlineA}
            onChange={(e) => setHeadlineA(e.target.value)}
            placeholder="Save 50% today"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Headline B
          <input
            value={headlineB}
            onChange={(e) => setHeadlineB(e.target.value)}
            placeholder="Members save half price this week"
            className={inputClass}
          />
        </label>
        <button
          type="submit"
          disabled={disabled}
          className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {loading ? "Asking the panel…" : "Evaluate"}
        </button>
      </form>

      {error && <p className="text-red-600">Error: {error}</p>}

      {result && (
        <section className="flex flex-col gap-4">
          <div className="rounded border border-zinc-200 p-4 dark:border-zinc-800">
            <p className="text-sm text-zinc-500">Winner</p>
            <p className="text-lg font-semibold">
              {result.variants[result.verdict.winner]}
            </p>
            <p className="mt-1 text-sm text-zinc-500">
              {Object.entries(result.verdict.counts)
                .map(([id, n]) => `${id.toUpperCase()}: ${n}`)
                .join(" · ")}{" "}
              · {result.verdict.total} votes
            </p>
          </div>

          <ul className="flex flex-col gap-2">
            {result.votes.map((vote) => (
              <li
                key={vote.persona_id}
                className="rounded border border-zinc-200 p-3 text-sm dark:border-zinc-800"
              >
                <span className="font-medium">
                  {vote.persona_id} → {vote.chosen_variant_id.toUpperCase()}
                </span>
                <p className="text-zinc-600 dark:text-zinc-400">{vote.reason}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
