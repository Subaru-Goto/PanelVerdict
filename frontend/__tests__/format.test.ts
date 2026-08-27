import { describe, expect, it } from "vitest";

import { formatPercent, formatPoints, formatSplit } from "../app/lib/format";

describe("formatPercent", () => {
  it("never rounds a probability up into a certainty", () => {
    // The live reading that found this: 23-2 of 25 puts P(A preferred) at
    // 0.9999947547912598, which `toFixed(0)` rendered as "100%" — a claim a
    // Beta posterior cannot make, from 25 synthetic votes.
    expect(formatPercent(0.9999947547912598)).toBe(">99%");
    expect(formatPercent(0.99990759)).toBe(">99%");
    expect(formatPercent(0.996)).toBe(">99%");
  });

  it("never rounds a probability down into an impossibility", () => {
    expect(formatPercent(5.245208740234375e-6)).toBe("<1%");
    expect(formatPercent(0.004)).toBe("<1%");
  });

  it("still says 0% and 100% when the value really is 0 or 1", () => {
    // The guard states a fact about the value, not an assumption about the
    // caller: a quantity that genuinely is none or all reads as none or all.
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(1)).toBe("100%");
  });

  it("rounds everything in between as before", () => {
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(0.9456)).toBe("95%");
    expect(formatPercent(0.0137)).toBe("1%");
  });
});

describe("formatSplit", () => {
  it("prints a pair that adds up", () => {
    // Found on the tie chart, where the caption read "50% prefer A · 51%
    // prefer B" — two shares that cannot both be true, printed directly above
    // a lead whose whole claim is that the two sides are equal. `toFixed`
    // rounds both halves of an even split up, so the pair gains a point.
    expect(formatSplit(0.505)).toEqual(["50%", "50%"]);
    expect(formatSplit(0.475)).toEqual(["52%", "48%"]);
    expect(formatSplit(0.288)).toEqual(["71%", "29%"]);
  });

  it("reads a panel and its mirror image alike", () => {
    // 100 of 198 and 98 of 198 are the same one-vote margin in opposite
    // directions, and both are credible ties. Rounding half *up* on the pair
    // would print 49/51 for one and 50/50 for the other — the same panel
    // reading as a dead heat or a two-point lead depending on which variant
    // happened to be called B.
    const [a, b] = formatSplit(0.505);
    expect(formatSplit(0.495)).toEqual([b, a]);
    expect([a, b]).toEqual(["50%", "50%"]);
  });

  it("keeps the overclaim guard on both ends", () => {
    // A pair summing to 100 is not worth a "0%" that the panel cannot support:
    // where either end trips `formatPercent`'s guard, both ends keep their own
    // reading and the pair is left alone.
    expect(formatSplit(0.9999947547912598)).toEqual(["<1%", ">99%"]);
    expect(formatSplit(0)).toEqual(["100%", "0%"]);
  });
});

describe("formatPoints", () => {
  it("keeps 0.0 — a difference of none is a real reading", () => {
    expect(formatPoints(0)).toBe("0.0 points");
    expect(formatPoints(0.211555)).toBe("21.2 points");
  });
});
