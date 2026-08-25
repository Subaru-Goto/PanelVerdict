import { accessToken } from "./auth";

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

export type Gender = "male" | "female";

/** Income travels as the band the vote prompt rendered — the prompt never
 *  mentions a quintile, so neither does the wire. */
export type IncomeBand = "lower" | "middle" | "upper";

/** The voter as a person: demographics verbatim, traits already bucketized to the
 *  same five levels the vote prompt was rendered from — never raw scores. Every
 *  voter is synthetic; the feed's copy says so where these fields show. */
export type VoterSummary = {
  country: Locale;
  age: number;
  gender: Gender;
  education: EducationLevel;
  income_band: IncomeBand;
  traits: Record<TraitName, TraitLevel>;
};

/** `persona_id` stays for reproducibility, but it identifies a row, not a reader —
 *  the feed leads with `voter` and never shows the id. */
export type Vote = {
  persona_id: string;
  chosen_variant_id: string;
  reason: string;
  voter: VoterSummary;
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
  gender: Gender | null;
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

export async function evaluate(
  request: EvaluateInput,
): Promise<EvaluateResponse> {
  // Same origin, through the proxy route (045/#143): the browser never learns
  // the backend URL or the edge secret — neither exists in this bundle.
  //
  // The session token does travel from here (063/#158), and it is the one
  // caller-supplied header the backend is right to read: everything else it
  // trusts has to be stamped by our proxy, because a caller could have written
  // it. A signed token is different in kind — the backend checks the signature
  // rather than the sender. Absent when nobody is signed in, and the refusal
  // that follows is the correct answer.
  const session = await accessToken();
  const res = await fetch("/api/evaluate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(session ? { Authorization: `Bearer ${session}` } : {}),
    },
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
    const body = (await res.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `API responded ${res.status}`,
    );
  }
  return (await res.json()) as EvaluateResponse;
}

/** How many runs today's account has left, or null if it could not be read.
 *
 * Null rather than zero on failure, deliberately: "0 runs left" tells someone
 * they are out of runs, and a failed read is not evidence of that.
 */
export async function remainingRuns(): Promise<number | null> {
  const session = await accessToken();
  if (!session) return null;
  const res = await fetch("/api/me", {
    headers: { Authorization: `Bearer ${session}` },
  });
  if (!res.ok) return null;
  const body = (await res.json().catch(() => null)) as {
    runs_remaining?: number;
  } | null;
  return typeof body?.runs_remaining === "number" ? body.runs_remaining : null;
}
