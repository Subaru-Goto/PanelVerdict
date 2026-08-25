"use client";

import type { PanelPreview } from "../lib/api";

/** The panel gate: who would be seated, and the choice to pay for them.
 *
 * Nothing has been bought when this renders. The plain layout is deliberate —
 * 093/#198 owns the designed version; this exists so the flow works end to end.
 */

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 text-sm">
      <span className="text-zinc-500">{label}</span>
      <span>{value}</span>
    </div>
  );
}

/** "male 3 · female 2" — the report's own vocabulary, so the two agree. */
function counted(groups: Record<string, number>): string {
  return Object.entries(groups)
    .map(([name, count]) => `${name.replace(/_/g, " ")} ${count}`)
    .join(" · ");
}

export default function PanelGate({
  preview,
  busy,
  onAccept,
  onBack,
}: {
  preview: PanelPreview;
  busy: boolean;
  onAccept: () => void;
  onBack: () => void;
}) {
  const { composition } = preview;
  const nobody = preview.matched === 0;

  return (
    <section className="flex flex-col gap-4 rounded border border-zinc-300 p-4 dark:border-zinc-700">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">Who would judge this</h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {nobody
            ? "Nobody in the pool matches this audience. Widen it and look again — nothing has been spent."
            : `${preview.matched} people match. Nothing has been spent yet.`}
        </p>
      </div>

      {composition && (
        <div className="flex flex-col gap-1">
          <Row
            label="Age"
            value={`${composition.age_min}–${composition.age_max} (median ${composition.age_median})`}
          />
          <Row label="Country" value={counted(composition.countries)} />
          <Row label="Gender" value={counted(composition.genders)} />
          <Row label="Education" value={counted(composition.education_levels)} />
          <Row label="Income" value={counted(composition.income_bands)} />
        </div>
      )}

      {preview.notices.map((notice) => (
        <p
          key={notice.message}
          className={
            notice.severity === "warning"
              ? "text-sm text-amber-700 dark:text-amber-500"
              : "text-sm text-zinc-600 dark:text-zinc-400"
          }
        >
          {notice.message}
        </p>
      ))}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onAccept}
          disabled={busy || nobody}
          className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {busy ? "Asking the panel…" : "Run the panel"}
        </button>
        <button
          type="button"
          onClick={onBack}
          disabled={busy}
          className="text-sm underline underline-offset-2 disabled:opacity-50"
        >
          Change the audience
        </button>
        <span className="ml-auto text-sm text-zinc-500">
          about ${preview.estimated_usd.toFixed(2)}
        </span>
      </div>
    </section>
  );
}
