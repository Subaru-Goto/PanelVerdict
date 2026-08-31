import { authHeaders } from "./auth";

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

/** Every locale the pool holds, and its age span — mirrors the backend's
 *  Locale enum and MIN/MAX_PERSONA_AGE. One place, so the form's controls and
 *  the gate's fact rows cannot drift apart. */
export const LOCALES: Locale[] = ["US", "JP", "DE"];
export const MIN_PANEL_AGE = 18;
export const MAX_PANEL_AGE = 100;

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
  /** The demographic controls (094): read by SQL, never by a model. Absent or
   *  empty means the whole pool — a real choice, not an omission. */
  target?: Partial<PanelEdit>;
  headlineA: string;
  headlineB: string;
  /** Who the readers are beyond anything the pool can be filtered by — life
   *  stage, habits, interests. Blank means demographics only and costs no
   *  model call (094/#200). */
  audience?: string;
  /** This reading was already approved, so the panel gate should not stop the
   *  run again. The client says it; the server never infers it. */
  readingAccepted?: boolean;
};

/** Who a run would seat and what it would cost, shown while the run holds at
 *  the gate — before anything is bought. */
export type PanelPreview = {
  query: TargetQuery;
  matched: number;
  composition: PanelComposition | null;
  notices: Notice[];
  /** The sentence every panelist will be told to be, or "" for a
   *  demographics-only run. Editable at the gate: what is approved here is
   *  exactly what runs. */
  instruction: string;
  /** Why the last edit was refused — our fixed sentence, never the edit. */
  refusal_sentence: string | null;
  estimated_usd: number;
};

/** Who is on the panel, in the same words the report uses. */
export type PanelComposition = {
  age_min: number;
  age_median: number;
  age_max: number;
  countries: Record<string, number>;
  genders: Record<string, number>;
  education_levels: Record<string, number>;
  income_bands: Record<string, number>;
};

/** A run either holds at the gate or finishes. Either call can return either:
 *  a resume pauses again when the reading was adjusted. */
export type EvaluateOutcome =
  | { status: "paused"; thread_id: string; preview: PanelPreview }
  | ({ status: "complete" } & EvaluateResponse);

/** The parts of a reading a human may edit at the gate.
 *
 * Narrower than `TargetQuery` on purpose: `coverage` and `notices` are the
 * report's account of how the words were read, not a filter, and the backend
 * refuses them here.
 */
export type PanelEdit = {
  countries: Locale[];
  min_age: number;
  max_age: number;
  gender: Gender | null;
  income_quintiles: number[];
  education: EducationLevel[];
  // No traits: temperament left targeting with the controls (094).
};

export type GateAnswer = {
  threadId: string;
  action: "accept" | "adjust";
  query?: PanelEdit;
  /** The role-play sentence as the reader left it. Absent means untouched —
   *  the case that costs no check, since the draft was classified when it was
   *  written. "" is a real answer: demographics only after all. */
  instruction?: string;
};

/** Read a proxy response as an outcome, or throw the backend's own sentence.
 *
 * The backend's refusals are safe to show: fixed sentences and exception type
 * names, never provider text.
 */
async function outcomeOf(res: Response): Promise<EvaluateOutcome> {
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `API responded ${res.status}`,
    );
  }
  const outcome = (await res.json()) as EvaluateOutcome;
  // Only a finished run spent one — a run holding at the gate bought nothing.
  if (outcome.status === "complete") {
    runsChanged.forEach((listener) => listener());
  }
  return outcome;
}

export async function evaluate(
  request: EvaluateInput,
): Promise<EvaluateOutcome> {
  // Same origin, through the proxy route (045/#143): the browser never learns
  // the backend URL or the edge secret — neither exists in this bundle.
  //
  // The session token does travel from here (063/#158), and it is the one
  // caller-supplied header the backend is right to read: everything else it
  // trusts has to be stamped by our proxy, because a caller could have written
  // it. A signed token is different in kind — the backend checks the signature
  // rather than the sender. Absent when nobody is signed in, and the refusal
  // that follows is the correct answer.
  const res = await fetch("/api/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({
      target: request.target ?? {},
      headline_a: request.headlineA,
      headline_b: request.headlineB,
      reading_accepted: request.readingAccepted ?? false,
      audience: request.audience ?? "",
    }),
  });
  return outcomeOf(res);
}

/** Answer the panel gate: accept and buy the votes, or adjust the reading.
 *
 * Carries the session, because this is the call that spends. */
export async function resumeEvaluate(
  answer: GateAnswer,
): Promise<EvaluateOutcome> {
  const res = await fetch("/api/evaluate/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({
      thread_id: answer.threadId,
      action: answer.action,
      ...(answer.query ? { query: answer.query } : {}),
      // undefined and "" diverge on the wire on purpose — see GateAnswer.
      ...(answer.instruction !== undefined
        ? { instruction: answer.instruction }
        : {}),
    }),
  });
  return outcomeOf(res);
}

/** Watch for the account's remaining runs changing. Returns an unsubscribe.
 *
 * Lives here because a run is the only thing that spends one. Without it the
 * figure keeps reading "3 runs left" after the run that made it 2. */
const runsChanged = new Set<() => void>();

export function onRunsChanged(listener: () => void): () => void {
  runsChanged.add(listener);
  return () => {
    runsChanged.delete(listener);
  };
}

/** How many runs today's account has left, or null if it could not be read.
 *
 * Null rather than zero: "0 runs left" would tell someone they are out when a
 * read simply failed. */
export async function remainingRuns(): Promise<number | null> {
  const headers = await authHeaders();
  // Nothing to ask about: a signed-out visitor has no count, and the call
  // would only ever come back 401.
  if (!("Authorization" in headers)) return null;
  const res = await fetch("/api/me", { headers });
  if (!res.ok) return null;
  const body = (await res.json().catch(() => null)) as {
    runs_remaining?: number;
  } | null;
  return typeof body?.runs_remaining === "number" ? body.runs_remaining : null;
}

/** One row of the account's own rail (117/#252).
 *
 * Three fragments of a stored report rather than the report: the rail shows
 * `"A" vs "B"` and a phrase derived from the verdict, and searches on the two
 * headlines. The votes stay on the server until a row is opened.
 *
 * No verdict *label* here, deliberately — `verdict.ts` derives it at render
 * time from these same numbers, so there is one threshold rather than two. */
export type StoredTest = {
  test_id: string;
  created_at: string;
  variants: Record<string, string>;
  verdict: PanelVerdict;
  tally: VoteTally;
};

async function jsonOrThrow(res: Response): Promise<unknown> {
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(
      typeof body?.detail === "string"
        ? body.detail
        : `API responded ${res.status}`,
    );
  }
  return res.json();
}

/** This account's finished tests, newest first. */
export async function myTests(): Promise<StoredTest[]> {
  const res = await fetch("/api/tests", { headers: await authHeaders() });
  return (await jsonOrThrow(res)) as StoredTest[];
}

/** One stored report, whole — what reopening a past test renders. */
export async function myTest(testId: string): Promise<EvaluateResponse> {
  const res = await fetch(`/api/tests/${encodeURIComponent(testId)}`, {
    headers: await authHeaders(),
  });
  return (await jsonOrThrow(res)) as EvaluateResponse;
}

/** Delete one stored test, for good.
 *
 * A 404 is not raised: the row is already gone, which is what the caller
 * wanted, and a second click on the × should not put an error on the page. */
export async function forgetTest(testId: string): Promise<void> {
  const res = await fetch(`/api/tests/${encodeURIComponent(testId)}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!res.ok && res.status !== 404) {
    throw new Error(`API responded ${res.status}`);
  }
}
