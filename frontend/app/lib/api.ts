export type VoteTally = {
  counts: Record<string, number>;
  total: number;
};

/** Preference-share points each choice risks. Never a monetary or click figure. */
export type PreferenceExposure = {
  shipping_a: number;
  shipping_b: number;
};

/** How likely each choice is to be the wrong one. Same shape as `PreferenceExposure`,
 *  different unit — a probability in 0-1, so `formatPercent` and never `formatPoints`. */
export type PreferenceProbability = {
  shipping_a: number;
  shipping_b: number;
};

export type PanelVerdict = {
  /** E[p] — the share of the panel expected to prefer B. */
  share_preferring_b: number;
  /** P(p > 0.5) — confidence that more than half do. A different question. */
  probability_majority_prefers_b: number;
  credible_interval: [number, number];
  credible_mass: number;
  /** The band this verdict was decided against; it travels with the verdict. */
  rope: [number, number];
  /** P(that choice loses by a gap the band would call worth having), each direction. */
  probability_worth_acting_on: PreferenceProbability;
  probability_practical_tie: number;
  /** Smallest gap this panel size could have called decisive; null if no split could. */
  detectable_gap: number | null;
  expected_preference_shortfall: PreferenceExposure;
};

export type Vote = {
  persona_id: string;
  chosen_variant_id: string;
  reason: string;
};

export type EvaluateResponse = {
  verdict: PanelVerdict;
  tally: VoteTally;
  variants: Record<string, string>;
  votes: Vote[];
};

export async function evaluate(
  headlineA: string,
  headlineB: string,
): Promise<EvaluateResponse> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ headline_a: headlineA, headline_b: headlineB }),
  });
  if (!res.ok) throw new Error(`API responded ${res.status}`);
  return (await res.json()) as EvaluateResponse;
}
