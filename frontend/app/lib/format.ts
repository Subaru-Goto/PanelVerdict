/** Every quantity this formats is a posterior mean, a probability or an HDI
 *  bound, all strictly inside (0, 1) by construction — so a rendered 0% or
 *  100% is always rounding claiming a certainty the panel cannot have. A live
 *  23-2 of 25 put P(A preferred) at 0.99999 and the report said "100%", which
 *  is the same overclaim in a different disguise.
 *
 *  Only the artifact is rewritten: an exact 0 or 1 still renders as itself, so
 *  the guard states a fact about the value rather than an assumption about
 *  who called it. */
const guarded = (value: number, percent: number): string | null =>
  percent === 100 && value < 1
    ? ">99%"
    : percent === 0 && value > 0
      ? "<1%"
      : null;

export const formatPercent = (value: number): string => {
  const percent = Number((value * 100).toFixed(0));
  return guarded(value, percent) ?? `${percent}%`;
};

/** Preference-share points, always with the unit — never a bare number. */
export const formatPoints = (value: number): string =>
  `${(value * 100).toFixed(1)} points`;

/** A complementary pair — "N% prefer A · M% prefer B" — rounded once, so the
 *  two always add up. Rounding each end on its own printed *50% prefer A · 51%
 *  prefer B* on an even panel, directly above a lead whose whole claim was
 *  that the two sides are equal: `toFixed` rounds both halves of an even split
 *  *up*, 49.5 to 50 and 50.5 to 51, and the pair gains a point.
 *
 *  Half to even, not half up, because the panel and its mirror image have to
 *  read alike: 100 of 198 and 98 of 198 are the same one-vote margin in
 *  opposite directions, and rounding half up would print 49/51 for one and
 *  50/50 for the other. Both read 50/50.
 *
 *  Where either end trips the overclaim guard, that end keeps its guarded
 *  reading: a pair that adds up is not worth printing a 0% the panel cannot
 *  support. Returns [A's share, B's share] for a `value` measured in B. */
export const formatSplit = (value: number): [string, string] => {
  const scaled = value * 100;
  const below = Math.floor(scaled);
  const percentB =
    scaled - below === 0.5
      ? below + (below % 2)
      : Math.round(scaled);
  const percentA = 100 - percentB;
  return [
    guarded(1 - value, percentA) ?? `${percentA}%`,
    guarded(value, percentB) ?? `${percentB}%`,
  ];
};
