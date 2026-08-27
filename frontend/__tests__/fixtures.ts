import type { EvaluateResponse } from "../app/lib/api";

/** One canonical response for tests, in WIRE units — every field as the backend
 *  sends it. `expected_preference_shortfall` is a fraction bounded by 0.5, never
 *  "points": writing the ×100 rendering into a fixture is how a units bug hides
 *  from every test that reads it. */
const BASE: EvaluateResponse = {
  verdict: {
    share_preferring_b: 0.288,
    probability_majority_prefers_b: 0.001,
    credible_interval: [0.173, 0.418],
    credible_mass: 0.95,
    rope: [0.43, 0.57],
    probability_meaningfully_preferred: { a: 0.984, b: 0.0 },
    probability_practical_tie: 0.016,
    detectable_gap: 0.167,
    expected_preference_shortfall: { shipping_a: 0.004, shipping_b: 0.212 },
  },
  tally: { counts: { a: 36, b: 14 }, total: 50 },
  counts: { requested: 200, matched: 200, voted: 50 },
  query: {
    countries: ["US", "JP", "DE"],
    coverage: "requested",
    min_age: 18,
    max_age: 100,
    gender: null,
    income_quintiles: [],
    education: [],
    traits: [],
    notices: [],
  },
  notices: [
    { severity: "warning", message: "2 of the 200 matched panelists did not vote." },
    {
      severity: "reading",
      // The backend's own sentence (`pipeline.py`, `_stopped_early_notice`),
      // not an abbreviation of it: the report used to repeat this claim in its
      // own words, unguarded, and the two could disagree.
      message:
        "Stopped after 50 of the 200 matched panelists: the panel had already " +
        "decided. The rest went unasked, so this is an answer, not a shortfall.",
    },
  ],
  stop_reason: "decisive",
  variants: { a: "Save 50% today", b: "Members save half" },
  votes: [
    {
      persona_id: "US-00042",
      chosen_variant_id: "a",
      reason: "<b>50% off</b> is the only thing here that changes my decision.",
      voter: {
        country: "US",
        age: 34,
        gender: "female",
        education: "tertiary",
        income_band: "upper",
        traits: {
          openness: "high",
          conscientiousness: "very_high",
          extraversion: "medium",
          agreeableness: "very_low",
          neuroticism: "low",
        },
      },
    },
  ],
};

/** A credible practical tie, and its mirror image — both taken whole from this
 *  project's own `panel_verdict(preferring_b=…, total=198)`, at the precision
 *  it returns. Hand-rounding the mean to 0.505 is what an earlier version of
 *  this fixture did, and the rounding was the only reason the caption under
 *  test appeared at all.
 *
 *  198 votes, because a tie has to be reachable: P(tie) first clears the 95%
 *  the report is stated at at 194 balanced votes, and the prod panel is 200.
 *  100-of-198 and 98-of-198 are the same one-vote margin in opposite
 *  directions — the second is here because every mark that switches on the
 *  leading side has a second half no B-leading fixture can reach.
 *
 *  Their means, 0.505 and 0.495, are the exact half-percents where rounding
 *  each end of the split on its own stops adding up. */
const tie = (
  verdict: EvaluateResponse["verdict"],
  counts: { a: number; b: number },
): EvaluateResponse => ({
  ...BASE,
  verdict,
  tally: { counts, total: 198 },
  counts: { requested: 200, matched: 198, voted: 198 },
  stop_reason: "practical_tie",
  notices: [],
  // Its own arrays: a fixture that hands out `BASE.votes` hands every test the
  // same array, and the first push lands in whichever test runs next.
  votes: [...BASE.votes],
  query: { ...BASE.query },
});

export const makeTiedResponse = (): EvaluateResponse =>
  tie(
    {
      share_preferring_b: 0.505,
      probability_majority_prefers_b: 0.5563484790092563,
      credible_interval: [0.4359402790958929, 0.5740314258556432],
      credible_mass: 0.95,
      rope: [0.43, 0.57],
      probability_meaningfully_preferred: {
        a: 0.016620600821272397,
        b: 0.03250018584295622,
      },
      probability_practical_tie: 0.9508792133357714,
      detectable_gap: 0.14,
      expected_preference_shortfall: {
        shipping_a: 0.01672799094983729,
        shipping_b: 0.011727990949837314,
      },
    },
    { a: 98, b: 100 },
  );

/** The same tie with the sides swapped — B by one becomes A by one. */
export const makeMirroredTie = (): EvaluateResponse =>
  tie(
    {
      share_preferring_b: 0.495,
      probability_majority_prefers_b: 0.44365152099074373,
      credible_interval: [0.4259685741443568, 0.5640597209041069],
      credible_mass: 0.95,
      rope: [0.43, 0.57],
      probability_meaningfully_preferred: {
        a: 0.0325001858429559,
        b: 0.01662060082127259,
      },
      probability_practical_tie: 0.9508792133357715,
      detectable_gap: 0.14,
      expected_preference_shortfall: {
        shipping_a: 0.011727990949837175,
        shipping_b: 0.01672799094983718,
      },
    },
    { a: 100, b: 98 },
  );

export const makeResponse = (
  overrides: Partial<EvaluateResponse> = {},
): EvaluateResponse => ({ ...BASE, ...overrides });


/** A /chat response whose NDJSON lines are fed one enqueue at a time, so a test
 *  can assert what the UI shows BETWEEN events — a transient status is only
 *  visible mid-stream. Shared, because the dock and the report both open
 *  conversations now. */
export const manualStream = () => {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200 }),
    push: (event: object) =>
      controller.enqueue(encoder.encode(JSON.stringify(event) + "\n")),
    close: () => controller.close(),
  };
};
