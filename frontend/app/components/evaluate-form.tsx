"use client";

import { useState, type FormEvent } from "react";

import { evaluate, type EvaluateResponse, type PanelVerdict } from "../lib/api";

/** Max, not B's: either direction can be the one worth acting on and the payload does not
 *  say which leads. */
const actionable = (verdict: PanelVerdict): number =>
  Math.max(
    verdict.probability_worth_acting_on.shipping_a,
    verdict.probability_worth_acting_on.shipping_b,
  );

type Recommendation = "lean" | "tie" | "no_call";

/** Derived here rather than delivered as a label, so the probability it rests on stays on
 *  screen beside it. The bar is the verdict's own `credible_mass` — the credibility
 *  everything else in the report is already stated at, so no second number is introduced
 *  that a reader would have to be told about separately. */
const recommend = (verdict: PanelVerdict): Recommendation => {
  if (actionable(verdict) >= verdict.credible_mass) return "lean";
  if (verdict.probability_practical_tie >= verdict.credible_mass) return "tie";
  return "no_call";
};

const HEADLINE: Record<Recommendation, string> = {
  lean: "Panel leans clearly",
  tie: "Practical tie",
  no_call: "No call at this credibility",
};

const ADVICE: Record<Recommendation, string> = {
  lean: "The lead is wide enough to be worth acting on.",
  tie: "Credibly too close to matter — pick either, or test a bolder variant.",
  no_call:
    "Read the probability above and decide against your own bar; more votes would sharpen it.",
};

/** Which variant the panel leans toward. B is only the reference, not the default. */
const LEADING_SIDE = (result: EvaluateResponse): "a" | "b" =>
  result.verdict.share_preferring_b >= 0.5 ? "b" : "a";

const leadingShare = (verdict: PanelVerdict): number =>
  Math.max(verdict.share_preferring_b, 1 - verdict.share_preferring_b);

const formatPercent = (value: number): string => `${(value * 100).toFixed(0)}%`;

/** Preference-share points, always with the unit — never a bare number. */
const formatPoints = (value: number): string =>
  `${(value * 100).toFixed(1)} points`;

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
          <div className="flex flex-col gap-2 rounded border border-zinc-200 p-4 dark:border-zinc-800">
            <p className="text-sm text-zinc-500">
              {HEADLINE[recommend(result.verdict)]}
            </p>
            <p className="text-lg font-semibold">
              {LEADING_SIDE(result) === "b"
                ? result.variants.b
                : result.variants.a}
            </p>
            <p className="text-sm">
              {formatPercent(leadingShare(result.verdict))} of the panel prefer
              it — {formatPercent(result.verdict.credible_mass)} credible
              interval {formatPercent(result.verdict.credible_interval[0])} to{" "}
              {formatPercent(result.verdict.credible_interval[1])}.
            </p>
            <p className="text-sm">
              {formatPercent(actionable(result.verdict))} chance the lead is
              worth acting on,{" "}
              {formatPercent(result.verdict.probability_practical_tie)} chance
              the two are too close to matter — called against a{" "}
              {formatPercent(result.verdict.credible_mass)} bar.
            </p>
            <p className="text-sm text-zinc-500">
              {ADVICE[recommend(result.verdict)]}
            </p>
            <p className="text-sm text-zinc-500">
              Picking A risks{" "}
              {formatPoints(
                result.verdict.expected_preference_shortfall.shipping_a,
              )}
              , picking B risks{" "}
              {formatPoints(
                result.verdict.expected_preference_shortfall.shipping_b,
              )}{" "}
              of panel preference. Treated as a tie within{" "}
              {formatPoints(0.5 - result.verdict.rope[0])} of even.
            </p>
            {result.verdict.detectable_gap !== null && (
              <p className="text-sm text-zinc-500">
                A panel this size can resolve a lean of{" "}
                {formatPoints(result.verdict.detectable_gap)} or more from even,
                so anything narrower reads as no call rather than as
                equivalence.
              </p>
            )}
            <p className="text-sm text-zinc-500">
              {Object.entries(result.tally.counts)
                .map(([id, n]) => `${id.toUpperCase()}: ${n}`)
                .join(" · ")}{" "}
              · {result.tally.total} votes
            </p>
            <p className="text-xs text-zinc-500">
              The panel chose <em>between</em> both headlines. Real readers
              usually see only one, so this is a preference share, not a
              predicted click-through rate — and it is unvalidated where two
              variants say the same thing differently.
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
                <p className="text-zinc-600 dark:text-zinc-400">
                  {vote.reason}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
