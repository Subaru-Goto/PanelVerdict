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
    { severity: "reading", message: "Stopped after 50 of the 200 matched panelists." },
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

/** A credible practical tie, every figure taken from the project's own
 *  `panel_verdict(preferring_b=101, total=200)` rather than typed by hand — a
 *  tie needs ~200 votes before the HDI fits inside the ±7-point band, so a
 *  50-vote fixture claiming one is arithmetic that could never occur. The
 *  panel is a hair off even, so the chart's peak and the band's centre are not
 *  the same x and a mark aimed at one cannot pass for a mark aimed at the
 *  other. */
export const makeTiedResponse = (): EvaluateResponse => ({
  ...BASE,
  verdict: {
    share_preferring_b: 0.505,
    probability_majority_prefers_b: 0.5561,
    credible_interval: [0.4362, 0.5736],
    credible_mass: 0.95,
    rope: [0.43, 0.57],
    probability_meaningfully_preferred: { a: 0.0162, b: 0.0317 },
    probability_practical_tie: 0.952,
    detectable_gap: 0.1386,
    expected_preference_shortfall: { shipping_a: 0.0166, shipping_b: 0.0117 },
  },
  tally: { counts: { a: 99, b: 101 }, total: 200 },
  counts: { requested: 200, matched: 200, voted: 200 },
  stop_reason: "practical_tie",
  notices: [],
});

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
