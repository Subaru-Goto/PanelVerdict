import { describe, expect, it } from "vitest";

import { posteriorDensity } from "../app/lib/beta";

describe("posteriorDensity", () => {
  it("samples the Beta(b+1, a+1) shape, scaled so the peak is 1", () => {
    // One vote each way → Beta(2, 2), density ∝ p(1−p). Worked by hand:
    // peak at p = 0.5 is 0.25; at p = 0.25 the raw value is 0.1875, so the
    // scaled density there must be 0.1875 / 0.25 = 0.75.
    const points = posteriorDensity(1, 1, 5);

    expect(points.map((point) => point.p)).toEqual([0, 0.25, 0.5, 0.75, 1]);
    expect(points[2].density).toBeCloseTo(1, 12);
    expect(points[1].density).toBeCloseTo(0.75, 12);
    expect(points[3].density).toBeCloseTo(0.75, 12);
    expect(points[0].density).toBe(0);
    expect(points[4].density).toBe(0);
  });

  it("survives a shutout — zero votes on one side puts the peak at the edge", () => {
    // 0 · ln(0) is NaN in JavaScript; a unanimous panel must not blank the
    // chart. Beta(1, 4), density ∝ (1−p)³: peak sits at p = 0, and the
    // hand-worked value at p = 0.5 is 0.125.
    const points = posteriorDensity(3, 0, 5);

    expect(points[0].density).toBe(1);
    expect(points[2].density).toBeCloseTo(0.125, 12);
    expect(points.every((point) => Number.isFinite(point.density))).toBe(true);
  });

  it("stays finite at tallies where the raw pdf underflows to zero", () => {
    // At 5000 votes the unnormalized density is ~e^-3300 everywhere — a
    // direct p^b(1−p)^a underflows to an all-zero curve and 0/0 = NaN. This
    // pins the log-space construction the 011 ticket decided.
    const points = posteriorDensity(3000, 2000, 101);

    const peak = Math.max(...points.map((point) => point.density));
    expect(peak).toBe(1);
    expect(points.every((point) => Number.isFinite(point.density))).toBe(true);
  });
});
