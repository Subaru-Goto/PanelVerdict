/** One line of a run's step stream — shared by the demo replay and the live
 *  waiting screen (021/#126), so the two runs a visitor can watch speak one
 *  visual language by construction. */
export function StepLine({
  label,
  done,
  sub,
}: {
  label: string;
  done: boolean;
  /** The line's right-hand fact — a captured duration, a live count. Absent
   *  means absent: an empty slot is honest, a printed zero is invented. */
  sub?: string;
}) {
  return (
    <p
      className={`flex items-baseline justify-between gap-4 border-b border-line py-[13px] text-[13px] font-semibold uppercase tracking-[0.08em] ${
        done ? "text-ink" : "text-ink-3"
      }`}
    >
      <span>
        {done ? "✓ " : ""}
        {label}
      </span>
      {sub !== undefined && (
        <span className="text-[11px] font-normal normal-case tracking-[0.04em] text-ink-3">
          {sub}
        </span>
      )}
    </p>
  );
}

/** The captured seconds, printed at the precision they carry: "45.3 s", and
 *  "90 ms" rather than a rounded-to-nothing "0.0 s". */
export function elapsed(seconds: number): string {
  return seconds >= 1
    ? `${seconds.toFixed(1)} s`
    : `${Math.round(seconds * 1000)} ms`;
}
