import { describe, expect, it } from "vitest";

import { formatPercent, formatPoints } from "../app/lib/format";

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

describe("formatPoints", () => {
  it("keeps 0.0 — a difference of none is a real reading", () => {
    expect(formatPoints(0)).toBe("0.0 points");
    expect(formatPoints(0.211555)).toBe("21.2 points");
  });
});
