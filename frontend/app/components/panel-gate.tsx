"use client";

import { useState } from "react";

import { type PanelPreview } from "../lib/api";
import { countryGroups, seatedCount, selectedFacts } from "../lib/reading";
import { CAPS, KICKER } from "../lib/styles";

/** The panel gate, as the prototype settles it (077): panel size and matched
 * count as plain numbers, each control echoed as a `Selected` fact, the
 * audience words tagged `Role-played`, the seating as stacked strips, and one
 * boxed decision. Nothing has been bought when this renders.
 */

function StatTile({
  kicker,
  number,
  unit,
  note,
}: {
  kicker: string;
  number: number;
  unit?: string;
  note: string;
}) {
  return (
    <div className="border-t-2 border-ink pt-[18px]">
      <p className={KICKER}>{kicker}</p>
      <p className="mt-2.5 text-[72px] font-light leading-none tracking-[-0.03em]">
        {number}
        {unit && (
          <small className="text-[22px] font-light text-ink-3"> {unit}</small>
        )}
      </p>
      <p className="mt-2.5 text-[13px] font-light text-ink-2">{note}</p>
    </div>
  );
}

function TraitRow({
  name,
  tag,
  value,
}: {
  name: string;
  tag: "Selected" | "Role-played";
  value: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line py-[13px] first:border-t">
      <span className="text-sm font-medium">
        {name}{" "}
        <span
          className={`${CAPS} whitespace-nowrap rounded-pill border px-2 py-0.5 font-bold ${
            tag === "Role-played"
              ? "border-amber text-amber"
              : "border-line text-ink-2"
          }`}
        >
          {tag}
        </span>
      </span>
      <span className="text-right text-[13px] font-light text-ink-2">
        {value}
      </span>
    </div>
  );
}

/** Light-to-dark across a strip, darkest always ink — the prototype's ramp in
 *  058's tokens. Three classes is the most any dimension has (api.ts). */
function ramp(n: number): string[] {
  const light = "bg-line text-ink";
  const mid = "bg-ink-2 text-surface";
  const dark = "bg-ink text-surface";
  if (n <= 1) return [dark];
  if (n === 2) return [light, dark];
  // Three classes is the most any dimension has today (api.ts); a wider
  // record just repeats the darkest rather than rendering unstyled.
  return [light, mid, ...Array<string>(n - 2).fill(dark)];
}

/** One dimension as a 100% stacked strip, every segment direct-labelled —
 *  chips would read fine at small sizes but a full panel would be a wall.
 *  Ordered classes keep their class order; the rest sort largest first. */
function Strip({
  label,
  groups,
  order,
}: {
  label: string;
  groups: Record<string, number>;
  order?: readonly string[];
}) {
  const total = Object.values(groups).reduce((sum, n) => sum + n, 0);
  const entries = Object.entries(groups).sort(
    order
      ? ([a], [b]) => order.indexOf(a) - order.indexOf(b)
      : ([, a], [, b]) => b - a,
  );
  const shades = ramp(entries.length);
  return (
    <div className="flex flex-col gap-1">
      <span className={`${CAPS} font-semibold text-ink-2`}>{label}</span>
      <div className="flex h-[26px] gap-0.5 overflow-hidden rounded-[3px]">
        {entries.map(([name, count], i) => (
          <span
            key={name}
            style={{ width: `${(count / total) * 100}%` }}
            // A sliver of a segment loses its printed label to overflow;
            // the title keeps the words reachable at any share.
            title={`${name.replace(/_/g, " ")} · ${Math.round((count / total) * 100)}%`}
            className={`flex min-w-0 items-center justify-center overflow-hidden whitespace-nowrap text-[10.5px] font-medium ${shades[i]}`}
          >
            {`${name.replace(/_/g, " ")} · ${Math.round((count / total) * 100)}%`}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function PanelGate({
  preview,
  audience = "",
  notice = null,
  onAccept,
  onBack,
}: {
  preview: PanelPreview;
  /** The audience words as submitted — the role-played row quotes them.
   *  The query carries only what they resolved to, never the words. */
  audience?: string;
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
  // explain (094). Shared with the echo under the form, so the two speak
  // identical words by construction.
  const selected = selectedFacts(query);
  // The trailing stop dropped, so the quote nests cleanly in a sentence.
  const words = audience.trim().replace(/\.$/, "");
  // Words alone are not enough for the row: the translator can map them
  // wholly onto demographics, and then there is no instruction below for the
  // row to point at — the paused thread's own draft is the source of truth.
  const rolePlayed = words !== "" && preview.instruction !== "";
  const seated = seatedCount(preview);

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
    <section className="flex flex-col gap-10">
      <p className="max-w-[560px] text-sm text-ink-2">
        Every trait you asked for, and what the pool did with it. Accept the
        reading, or adjust it and come back. The votes are bought only when you
        accept, and an audience you have already accepted is not asked about
        twice.
      </p>

      {nobody && (
        <p className="text-sm text-amber">
          Nobody in the pool matches this audience. Widen it and look again —
          nothing has been spent.
        </p>
      )}

      <div className="grid gap-14 md:grid-cols-[280px_1fr]">
        <div className="flex flex-col gap-9 self-start">
          <StatTile
            kicker="Panel size"
            number={seated}
            note="readers, each voting once and giving a reason"
          />
          <StatTile
            kicker="Drawn from"
            number={preview.matched}
            unit="matched"
            note="personas in the pool that fit the description you gave"
          />
        </div>

        <div className="flex flex-col gap-7">
          <div>
            <p className={`${KICKER} mb-1`}>What the pool could match</p>
            {selected.length === 0 && !rolePlayed ? (
              <p className="py-3 text-sm text-ink-2">
                Everyone in the pool — no control narrowed anything.
              </p>
            ) : (
              <>
                {selected.map(([label, value]) => (
                  <TraitRow
                    key={label}
                    name={label}
                    tag="Selected"
                    value={value}
                  />
                ))}
                {rolePlayed && (
                  <TraitRow
                    name={`“${words}”`}
                    tag="Role-played"
                    value="no data to pick them by — acted instead, per the instruction below"
                  />
                )}
              </>
            )}
          </div>

          {preview.notices.map((note) => (
            <p
              key={note.message}
              className={
                note.severity === "warning"
                  ? "text-sm text-amber"
                  : "text-sm text-ink-2"
              }
            >
              {note.message}
            </p>
          ))}

          {preview.instruction !== "" && (
            <label className="flex flex-col gap-2 text-sm">
              <span className={KICKER}>
                The instruction each panelist will act
              </span>
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={2}
                // Mirrors MAX_INSTRUCTION_CHARS (schemas.py): the backend
                // refuses longer, so the field should not let it be typed.
                maxLength={400}
                className="rounded border border-line px-3 py-2"
              />
              <span className="text-xs text-ink-2">
                Role-played, not sampled: each panelist acts this on top of
                their surveyed age, gender, education and income — no data
                picked them by it. Edit it, or clear it to run on demographics
                alone; what you approve is exactly what the panel is told.
              </span>
              {touched && (
                <span className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                  <button
                    type="button"
                    onClick={() => setInstruction(preview.instruction)}
                    className="text-xs underline underline-offset-2"
                  >
                    Restore the model&rsquo;s draft
                  </button>
                  {/* Edits bypass the rewrite model, so the answer is screened
                      before any vote is bought — and that screening is what a
                      check budget counts (077). */}
                  <span className="text-xs text-ink-3">
                    Edited text is checked before it runs, against its own daily
                    budget — a refused check still counts.
                  </span>
                </span>
              )}
            </label>
          )}

          {/* One slot, two sources: a refusal caught on this client (notice) or
              one the pause already carried (a resumed thread). Ours either way —
              never the refused text. */}
          {(notice ?? preview.refusal_sentence) && (
            <p
              role="alert"
              // report.tsx's notice idiom, so refusals look alike app-wide.
              className="rounded border-l-4 border-red bg-red/5 p-3 text-sm"
            >
              {notice ?? preview.refusal_sentence}
            </p>
          )}
        </div>
      </div>

      {composition && (
        <div className="flex flex-col gap-3.5">
          <div>
            <p className={KICKER}>Who ends up seated</p>
            <p className="text-xs font-light text-ink-3">
              The panel&rsquo;s make-up inside your filters.
            </p>
          </div>
          {/* Age is a span, not classes — the one dimension without a strip. */}
          <div className="flex flex-col gap-1">
            <span className={`${CAPS} font-semibold text-ink-2`}>Age</span>
            <span className="text-[13px] font-light text-ink-2">
              {composition.age_min}–{composition.age_max} (median{" "}
              {composition.age_median})
            </span>
          </div>
          <Strip
            label="Country"
            groups={countryGroups(composition.countries)}
          />
          <Strip label="Gender" groups={composition.genders} />
          <Strip
            label="Education"
            groups={composition.education_levels}
            order={["below_secondary", "secondary", "tertiary"]}
          />
          <Strip
            label="Income"
            groups={composition.income_bands}
            order={["lower", "middle", "upper"]}
          />
        </div>
      )}

      {/* The one boxed decision on the whole site. Panel size is the system's,
          not a knob — it moves the statistics, so runs stay comparable. */}
      <div className="border border-ink px-6 py-7 sm:px-10 sm:py-9">
        <h2>Approve this reading?</h2>
        <p className="mt-2 max-w-[560px] text-sm font-light text-ink-2">
          Accepting starts the run. Each reader casts one vote, and a run is the
          unit your daily allowance is counted in.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-3.5">
          <button
            type="button"
            onClick={accept}
            disabled={sent || nobody}
            className="rounded-pill bg-ink px-6 py-2.5 text-sm font-medium text-surface disabled:bg-surface-2 disabled:text-ink-3"
          >
            {sent ? "Asking the panel…" : "Looks right — run the panel"}
          </button>
          <button
            type="button"
            onClick={onBack}
            disabled={sent}
            className="rounded-pill border border-ink px-6 py-2.5 text-sm font-medium disabled:opacity-50"
          >
            Adjust the audience
          </button>
        </div>
        <p className="mt-[22px] text-xs font-light text-ink-3">
          The votes are bought only when you accept. If you wrote an audience,
          one small call turned it into the instruction above — that call is the
          only spend so far, and it repeats only when your words change, never
          per run.
        </p>
      </div>
    </section>
  );
}
