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
