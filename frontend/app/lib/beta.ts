export type DensityPoint = { p: number; density: number };

export function posteriorDensity(
  votesA: number,
  votesB: number,
  samples: number,
): DensityPoint[] {
  // 0 · ln(0) is NaN, but a zero exponent means the factor is 1 — so its
  // log-term is 0, whatever p is.
  const xlogy = (x: number, y: number): number => (x === 0 ? 0 : x * Math.log(y));

  const grid = Array.from({ length: samples }, (_, i) => i / (samples - 1));
  const logs = grid.map((p) => xlogy(votesB, p) + xlogy(votesA, 1 - p));
  const peak = Math.max(...logs);
  return grid.map((p, i) => ({ p, density: Math.exp(logs[i] - peak) }));
}
