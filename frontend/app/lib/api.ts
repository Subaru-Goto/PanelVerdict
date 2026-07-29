export type VoteTally = {
  counts: Record<string, number>;
  total: number;
};

/** Preference-share points each choice risks. Never a monetary or click figure. */
export type PreferenceExposure = {
  shipping_a: number;
  shipping_b: number;
};

/** P(that variant is preferred by more than the band), per variant. A probability in
 *  0-1, so `formatPercent` and never `formatPoints` — the key sets differing from
 *  `PreferenceExposure`'s is what keeps the two units apart. */
export type PreferenceProbability = {
  a: number;
  b: number;
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
  /** P(that variant is preferred by a gap the band would call worth having). */
  probability_meaningfully_preferred: PreferenceProbability;
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

/** `warning` means the panel is not the one asked for; `reading` means it is, and
 *  here is the interpretation it rests on. Different treatment, not just styling. */
export type Notice = {
  severity: "warning" | "reading";
  message: string;
};

export type TraitName =
  | "openness"
  | "conscientiousness"
  | "extraversion"
  | "agreeableness"
  | "neuroticism";

export type TraitLevel = "very_low" | "low" | "medium" | "high" | "very_high";

/** One Big Five level read out of the target, with the words it was read from —
 *  `source_phrase` is the only part of the interpretation a customer can check. */
export type TraitRequest = {
  trait: TraitName;
  level: TraitLevel;
  source_phrase: string;
};

/** What `countries` cannot say on its own: a panel spanning the whole pool is
 *  byte-identical whether no country was named (`requested`) or the named one could
 *  not be served at all (`unmatched`). The report must read this, never just the list. */
export type CoverageRung = "requested" | "approximated" | "unmatched";

export type Locale = "US" | "JP" | "DE";

export type EducationLevel = "below_secondary" | "secondary" | "tertiary";

export type TargetQuery = {
  countries: Locale[];
  coverage: CoverageRung;
  min_age: number;
  max_age: number;
  gender: "male" | "female" | null;
  income_quintiles: number[];
  education: EducationLevel[];
  traits: TraitRequest[];
  notices: Notice[];
};

/** Each pair answers a different question: requested vs matched is the target being
 *  narrower than the pool; matched vs voted is the model failing. Only `voted`
 *  carries the verdict. */
export type PanelCounts = {
  requested: number;
  matched: number;
  voted: number;
};

export type StopReason = "decisive" | "practical_tie";

export type EvaluateResponse = {
  verdict: PanelVerdict;
  tally: VoteTally;
  counts: PanelCounts;
  query: TargetQuery;
  notices: Notice[];
  /** An early stop is a fact about the run, not a shortfall — data, so the report
   *  can distinguish "stopped because answered" without parsing prose. */
  stop_reason: StopReason | null;
  variants: Record<string, string>;
  votes: Vote[];
};

/** An object rather than three same-typed positional strings — a swap would
 *  type-check. Named once here; the hook reuses it. */
export type EvaluateInput = {
  targetDescription: string;
  headlineA: string;
  headlineB: string;
};

export async function evaluate(request: EvaluateInput): Promise<EvaluateResponse> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_description: request.targetDescription,
      headline_a: request.headlineA,
      headline_b: request.headlineB,
    }),
  });
  if (!res.ok) {
    // The backend's refusals are written for humans and safe by construction
    // (fixed sentences and exception type names — never provider text), so the
    // detail is the error message when present.
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `API responded ${res.status}`,
    );
  }
  return (await res.json()) as EvaluateResponse;
}
