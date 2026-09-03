/** The two notice looks (the prototype's, 058): a warning is red-edged, the
 *  rest sit on the second surface. One place, so a notice on the form and a
 *  notice in the report cannot drift apart. */
export function noticeClass(severity: "warning" | "info"): string {
  return severity === "warning"
    ? "rounded border-l-4 border-dotted border-red bg-red/5 p-2 text-sm"
    : "rounded border-l-4 border-line bg-surface-2 p-2 text-sm text-ink-2";
}
