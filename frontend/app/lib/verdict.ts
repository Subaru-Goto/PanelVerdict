import type { PanelVerdict } from "./api";

/** Which variant the panel leans toward. B is only the reference direction the
 *  payload is written in, never the default answer.
 *
 *  Shared, because the lead states this side's probability in words and the
 *  chart shades this side's tail — and the two disagreeing would put the
 *  winner's figure on the loser's area.
 *
 *  The 0.5 split matches the chart's tie band only because that band is
 *  symmetric about 0.5 (`_ROPE = (0.43, 0.57)`, backend `verdict.py`). An
 *  asymmetric band would need this to split at its nearer edge instead. */
export const leadingSide = (verdict: PanelVerdict): "a" | "b" =>
  verdict.share_preferring_b >= 0.5 ? "b" : "a";

/** Whether "these two are equally good" is itself a credible finding: the tie's
 *  own probability clearing the credibility everything else on the page is
 *  stated at. 020 keeps it a flag, not a bucket — it adds a line to the lead
 *  and moves the chart's annotation, it never replaces the probability.
 *
 *  Shared for the same reason as `leadingSide`: the lead's sentence and the
 *  chart's annotation have to switch together, and a chart still writing the
 *  leader's figure under a lead saying the two are equal is the report
 *  disagreeing with itself. */
export const isPracticalTie = (verdict: PanelVerdict): boolean =>
  verdict.probability_practical_tie >= verdict.credible_mass;

/** The one-line summary the rail puts under a past test's headlines — "71%
 *  preferred the first", "too close to call" (117/#252).
 *
 *  Derived here rather than sent by the backend, and derived from the same two
 *  helpers the report itself uses: a phrase computed server-side would be a
 *  second threshold to keep in step with `isPracticalTie`, and 020 keeps the
 *  label out of the payload. So a rail row and the report it opens can never
 *  disagree about whether the panel called it.
 *
 *  Named "first"/"second" rather than A/B because the rail shows the headlines
 *  themselves, in that order — a reader scanning it has no A and B to map. */
export const railSummary = (verdict: PanelVerdict): string => {
  if (isPracticalTie(verdict)) return "too close to call";
  const leading = leadingSide(verdict);
  const share =
    leading === "b"
      ? verdict.share_preferring_b
      : 1 - verdict.share_preferring_b;
  return `${Math.round(share * 100)}% preferred the ${
    leading === "b" ? "second" : "first"
  }`;
};
