/** Every quantity this formats is a posterior mean, a probability or an HDI
 *  bound, all strictly inside (0, 1) by construction — so a rendered 0% or
 *  100% is always rounding claiming a certainty the panel cannot have. A live
 *  23-2 of 25 put P(A preferred) at 0.99999 and the report said "100%", which
 *  is the same overclaim in a different disguise.
 *
 *  Only the artifact is rewritten: an exact 0 or 1 still renders as itself, so
 *  the guard states a fact about the value rather than an assumption about
 *  who called it. */
export const formatPercent = (value: number): string => {
  const percent = Number((value * 100).toFixed(0));
  if (percent === 100 && value < 1) return ">99%";
  if (percent === 0 && value > 0) return "<1%";
  return `${percent}%`;
};

/** Preference-share points, always with the unit — never a bare number. */
export const formatPoints = (value: number): string =>
  `${(value * 100).toFixed(1)} points`;
