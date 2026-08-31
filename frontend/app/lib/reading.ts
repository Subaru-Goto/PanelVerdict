import {
  LOCALES,
  MAX_PANEL_AGE,
  MIN_PANEL_AGE,
  type EvaluateInput,
  type Locale,
  type PanelEdit,
  type PanelPreview,
  type TargetQuery,
} from "./api";

/** The pool's three countries in the reader's words. One map, used by the
 *  form's controls, the gate's fact rows and the echo — same words before and
 *  after the money (023). */
export const COUNTRY_LABELS: Record<Locale, string> = {
  US: "United States",
  JP: "Japan",
  DE: "Germany",
};

/** The selections that narrowed the pool, as [label, value] rows — the gate's
 *  facts and the echo's phrases come from this one builder, so they cannot
 *  drift apart. A control that narrowed nothing is not a row: every country
 *  and the full age span is just the pool. */
export function selectedFacts(query: TargetQuery): [string, string][] {
  const rows: [string, string][] = [];
  if (!LOCALES.every((code) => query.countries.includes(code)))
    rows.push([
      "Country",
      query.countries.map((code) => COUNTRY_LABELS[code]).join(", "),
    ]);
  if (query.min_age !== MIN_PANEL_AGE || query.max_age !== MAX_PANEL_AGE)
    rows.push(["Age", `${query.min_age}–${query.max_age}`]);
  if (query.gender) rows.push(["Gender", query.gender]);
  if (query.education.length)
    rows.push(["Education", query.education.join(", ").replace(/_/g, " ")]);
  if (query.income_quintiles.length)
    rows.push([
      "Income",
      query.income_quintiles.map((q) => `Q${q}`).join(", "),
    ]);
  return rows;
}

/** Every control as the wire wants it: the form's absent-means-everything
 *  defaults made explicit, in one place — `readingKey` serializes this, and a
 *  resume that replaces the whole reading sends it. */
export function settledEdit(request: EvaluateInput): PanelEdit {
  const target = request.target ?? {};
  return {
    countries: target.countries ?? [],
    min_age: target.min_age ?? MIN_PANEL_AGE,
    max_age: target.max_age ?? MAX_PANEL_AGE,
    gender: target.gender ?? null,
    income_quintiles: target.income_quintiles ?? [],
    education: target.education ?? [],
  };
}

/** The audience as an identity (077/#167): every control plus the words.
 *
 * The gate fires once per audience, and "same audience" has to mean something
 * exact — this string is it. Two requests with equal keys seat the same
 * panel, person for person (the sample is seeded), so a reading approved
 * under one is approved under the other.
 */
export function readingKey(request: EvaluateInput): string {
  const edit = settledEdit(request);
  return JSON.stringify({
    countries: [...edit.countries].sort(),
    min_age: edit.min_age,
    max_age: edit.max_age,
    gender: edit.gender,
    education: [...edit.education].sort(),
    income: [...edit.income_quintiles].sort(),
    audience: (request.audience ?? "").trim(),
  });
}

/** One line naming an accepted reading — "25–40 · Japan · 5 seated": the
 *  gate's own fact rows, joined. Built from `selectedFacts`, so the echo and
 *  the gate speak identical words by construction. */
export function readingSummary(preview: PanelPreview): string {
  const { composition } = preview;
  // Seats are counted from who is actually sitting; a preview that seated
  // nobody (composition null) can only name how many matched.
  const seated = composition
    ? Object.values(composition.countries).reduce((sum, n) => sum + n, 0)
    : preview.matched;
  return [
    ...selectedFacts(preview.query).map(([, value]) => value),
    `${seated} seated`,
  ].join(" · ");
}
