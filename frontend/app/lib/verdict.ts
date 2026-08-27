import type { PanelVerdict } from "./api";

/** Which variant the panel leans toward. B is only the reference direction the
 *  payload is written in, never the default answer.
 *
 *  Shared, because the lead states this side's probability in words and the
 *  chart shades this side's tail — and the two disagreeing would put the
 *  winner's figure on the loser's area. */
export const leadingSide = (verdict: PanelVerdict): "a" | "b" =>
  verdict.share_preferring_b >= 0.5 ? "b" : "a";
