export const formatPercent = (value: number): string =>
  `${(value * 100).toFixed(0)}%`;

/** Preference-share points, always with the unit — never a bare number. */
export const formatPoints = (value: number): string =>
  `${(value * 100).toFixed(1)} points`;
