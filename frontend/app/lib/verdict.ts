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
