/** The prototype's two small-caps label styles (docs/design/prototype.html:
 *  `.kicker` 11px/.18em/500, `.comp-k`/`.tag` 10px/.14em), as one vocabulary —
 *  they were being hand-copied per component, and copies drift. Weight is
 *  deliberately not part of CAPS: the prototype's tag is 700 where its strip
 *  labels are 600, so each use says its own. */
export const KICKER =
  "text-[11px] font-medium uppercase tracking-[0.18em] text-ink-2";
export const CAPS = "text-[10px] uppercase tracking-[0.14em]";
