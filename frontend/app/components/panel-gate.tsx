"use client";

import { useState } from "react";

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
  notice = null,
  onAccept,
  onBack,
}: {
  preview: PanelPreview;
  /** The backend's fixed refusal sentence when the last answer was turned
   *  away. The run is still paused, so the gate re-arms for another try. */
  notice?: string | null;
  onAccept: (instruction?: string) => void | Promise<void>;
  onBack: () => void;
}) {
  // Disables itself rather than taking a prop for it. Two clicks land before
  // React swaps this view out, and each one would buy the panel.
  const [sent, setSent] = useState(false);
  // The sentence each panelist will be told to be, as the reader leaves it.
  // Editing it is the human-in-the-loop (094/#200): what is approved here is
  // exactly what runs. Seeded from the prop and never re-synced — safe while a
  // pause's draft cannot change (refusals keep the preview); if adjust ever
  // regenerates it, key this component by the preview or the stale text will
  // read as an edit and buy a check.
  const [instruction, setInstruction] = useState(preview.instruction);
  const touched = instruction !== preview.instruction;
  const { composition, query } = preview;
  const nobody = preview.matched === 0;

  // The reading as fact rows: the caller's own controls, no interpretation to
  // explain (094). A control that narrowed nothing is not a row — every
  // country and the full age span is just the pool.
  const everyCountry = ["US", "JP", "DE"].every((c) =>
    (query.countries as string[]).includes(c),
  );
  const selected: [string, string][] = [];
  if (!everyCountry) selected.push(["Country", query.countries.join(", ")]);
  if (query.min_age !== 18 || query.max_age !== 100)
    selected.push(["Age", `${query.min_age}–${query.max_age}`]);
  if (query.gender) selected.push(["Gender", query.gender]);
  if (query.education.length)
    selected.push(["Education", query.education.join(", ").replace(/_/g, " ")]);
  if (query.income_quintiles.length)
    selected.push([
      "Income",
      query.income_quintiles.map((q) => `Q${q}`).join(", "),
    ]);

  function accept(): void {
    setSent(true);
    // Untouched rides as absence — no check to pay for; any change, including
    // clearing to "", is a real answer the backend classifies before spending.
    // Re-arm if the answer is refused: the gate survives its own rejection.
    void Promise.resolve(onAccept(touched ? instruction : undefined)).finally(
      () => setSent(false),
    );
  }

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

      <div className="flex flex-col gap-1">
        <h3 className="text-sm font-medium">Selected</h3>
        {selected.length === 0 ? (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Everyone in the pool — no control narrowed anything.
          </p>
        ) : (
          selected.map(([label, value]) => (
            <Row key={label} label={label} value={value} />
          ))
        )}
      </div>

      {composition && (
        <div className="flex flex-col gap-1">
          {/* Who the selection actually seated — the draw, not the ask. */}
          <h3 className="text-sm font-medium">Seated</h3>
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

      {preview.notices.map((note) => (
        <p
          key={note.message}
          className={
            note.severity === "warning"
              ? "text-sm text-amber-700 dark:text-amber-500"
              : "text-sm text-zinc-600 dark:text-zinc-400"
          }
        >
          {note.message}
        </p>
      ))}

      {preview.instruction !== "" && (
        <label className="flex flex-col gap-1 text-sm">
          What each panelist will be told
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            rows={2}
            // Mirrors MAX_INSTRUCTION_CHARS (schemas.py): the backend refuses
            // longer, so the field should not let it be typed.
            maxLength={400}
            className="rounded border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900"
          />
          <span className="text-xs text-zinc-500">
            Role-played, not sampled: each panelist acts this on top of their
            surveyed age, gender, education and income — no data picked them by
            it. Edit it, or clear it to run on demographics alone; what you
            approve is exactly what the panel is told.
          </span>
          {touched && (
            <button
              type="button"
              onClick={() => setInstruction(preview.instruction)}
              className="self-start text-xs underline underline-offset-2"
            >
              Restore the draft
            </button>
          )}
        </label>
      )}

      {/* One slot, two sources: a refusal caught on this client (notice) or
          one the pause already carried (a resumed thread). Ours either way —
          never the refused text. */}
      {(notice ?? preview.refusal_sentence) && (
        <p role="alert" className="text-sm text-amber-700 dark:text-amber-500">
          {notice ?? preview.refusal_sentence}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={accept}
          disabled={sent || nobody}
          className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {sent ? "Asking the panel…" : "Run the panel"}
        </button>
        <button
          type="button"
          onClick={onBack}
          disabled={sent}
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
