"use client";

import { useEffect, useState, type SubmitEvent } from "react";

import {
  LOCALES,
  MAX_PANEL_AGE,
  MIN_PANEL_AGE,
  type EducationLevel,
  type Gender,
  type Locale,
} from "../lib/api";
import { AI_SYSTEM_DISCLOSURE } from "../lib/disclosure";
import PastTests from "./past-tests";
import { useEvaluate } from "../lib/use-evaluate";
import PanelGate from "./panel-gate";
import Report from "./report";

const INPUT_CLASS = "rounded border border-line px-3 py-2";

function Field({
  label,
  value,
  onChange,
  placeholder,
  multiline = false,
  maxLength,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  multiline?: boolean;
  maxLength?: number;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label}
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={2}
          maxLength={maxLength}
          className={INPUT_CLASS}
        />
      ) : (
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={INPUT_CLASS}
        />
      )}
    </label>
  );
}

/** One choice in a multi-choice control: a labeled checkbox that adds or
 *  removes its value. Checking nothing means "any" — the pool unfiltered. */
function Choice<T extends string | number>({
  label,
  value,
  chosen,
  onChange,
}: {
  label: string;
  value: T;
  chosen: T[];
  onChange: (next: T[]) => void;
}) {
  const checked = chosen.includes(value);
  return (
    <label className="flex items-center gap-1.5 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={() =>
          onChange(
            checked ? chosen.filter((c) => c !== value) : [...chosen, value],
          )
        }
      />
      {label}
    </label>
  );
}

/** Proof that a run is alive, not frozen.
 *
 *  A disabled button looks identical whether the panel is voting or the
 *  request died, which is exactly how a slow run gets read as a broken one. A
 *  number that keeps moving settles it, and it costs the backend nothing — no
 *  streaming, no progress endpoint, no estimate that could be wrong.
 *
 *  Deliberately not a percentage: nothing here knows how far along the run is,
 *  and a bar that guesses would be a worse lie than no bar at all. */
function Waiting() {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <p
      role="status"
      className="flex items-center gap-2 text-sm text-ink-2"
      aria-live="polite"
    >
      <span
        aria-hidden
        className="h-2 w-2 animate-pulse rounded-full bg-ink-3"
      />
      Each panelist is reading both headlines and picking one — {seconds}s so
      far.
    </p>
  );
}

export default function EvaluateForm({
  // Passed in from the server-rendered page rather than fetched here, so the
  // line is in the first paint. A disclosure arriving after hydration leaves a
  // window in which someone has already typed.
  tracing = false,
}: {
  tracing?: boolean;
}) {
  // The demographic controls (094): read straight into SQL, no model involved.
  // Nothing chosen means the whole pool — a real choice, not an omission.
  const [countries, setCountries] = useState<Locale[]>([]);
  const [minAge, setMinAge] = useState(MIN_PANEL_AGE);
  const [maxAge, setMaxAge] = useState(MAX_PANEL_AGE);
  const [gender, setGender] = useState<"" | Gender>("");
  const [education, setEducation] = useState<EducationLevel[]>([]);
  const [incomeQuintiles, setIncomeQuintiles] = useState<number[]>([]);
  const [audience, setAudience] = useState("");
  const [headlineA, setHeadlineA] = useState("");
  const [headlineB, setHeadlineB] = useState("");
  const { state, submit, answerGate, reset, show } = useEvaluate();

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit({
      target: {
        countries,
        min_age: minAge,
        max_age: maxAge,
        gender: gender || null,
        education,
        income_quintiles: incomeQuintiles,
      },
      audience,
      headlineA,
      headlineB,
    });
  }

  // A cleared number input coerces to 0 and an inverted pair matches nobody;
  // the backend refuses both, but a submit that cannot succeed should not be
  // clickable.
  const agesValid =
    minAge >= MIN_PANEL_AGE && maxAge <= MAX_PANEL_AGE && minAge <= maxAge;

  // Both audience fields stay optional: two headlines against a cross-section
  // of the whole pool is a real test, and blank is a choice rather than an
  // omission. The backend calls no model at all for an empty audience.
  const disabled =
    !headlineA.trim() ||
    !headlineB.trim() ||
    !agesValid ||
    state.phase === "loading";

  // Once a report exists the page stops being a form: the reader wants the
  // answer at the top rather than the inputs they already filled in.
  if (state.phase === "done") {
    return (
      <div className="flex flex-col gap-6">
        <button
          type="button"
          onClick={reset}
          className="self-start rounded border border-line px-3 py-1.5 text-sm"
        >
          Test again
        </button>
        <Report result={state.result} />
        <PastTests onOpen={show} />
      </div>
    );
  }

  // Holding at the gate: the reader decides whether to buy the votes.
  if (state.phase === "gated") {
    return (
      <div className="flex flex-col gap-4">
        <PanelGate
          preview={state.preview}
          notice={state.notice ?? null}
          // Returned, not voided: the gate re-arms its button when this
          // settles, and a swallowed promise would re-arm it mid-spend.
          onAccept={(instruction) =>
            answerGate("accept", undefined, instruction)
          }
          onBack={reset}
        />
        {state.resuming && <Waiting />}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <fieldset className="flex flex-col gap-2 rounded border border-line p-3 text-sm">
          <legend className="px-1">
            Who should judge these? Leave a control alone to mean anyone.
          </legend>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-ink-2">Country</span>
            {LOCALES.map((code) => (
              <Choice
                key={code}
                label={
                  { US: "United States", JP: "Japan", DE: "Germany" }[code]
                }
                value={code}
                chosen={countries}
                onChange={setCountries}
              />
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5">
              Age from
              <input
                type="number"
                min={MIN_PANEL_AGE}
                max={MAX_PANEL_AGE}
                value={minAge}
                onChange={(e) => setMinAge(Number(e.target.value))}
                className={`${INPUT_CLASS} w-20`}
              />
            </label>
            <label className="flex items-center gap-1.5">
              Age to
              <input
                type="number"
                min={MIN_PANEL_AGE}
                max={MAX_PANEL_AGE}
                value={maxAge}
                onChange={(e) => setMaxAge(Number(e.target.value))}
                className={`${INPUT_CLASS} w-20`}
              />
            </label>
            <label className="flex items-center gap-1.5">
              Gender
              <select
                value={gender}
                onChange={(e) => setGender(e.target.value as "" | Gender)}
                className={INPUT_CLASS}
              >
                <option value="">any</option>
                <option value="female">female</option>
                <option value="male">male</option>
              </select>
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-ink-2">Education</span>
            <Choice
              label="below secondary"
              value="below_secondary"
              chosen={education}
              onChange={setEducation}
            />
            <Choice
              label="secondary"
              value="secondary"
              chosen={education}
              onChange={setEducation}
            />
            <Choice
              label="tertiary"
              value="tertiary"
              chosen={education}
              onChange={setEducation}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {/* Quintiles, lowest to highest — the pool's own income shape. */}
            <span className="text-ink-2">Income</span>
            <Choice
              label="Q1 (lowest)"
              value={1}
              chosen={incomeQuintiles}
              onChange={setIncomeQuintiles}
            />
            <Choice
              label="Q2"
              value={2}
              chosen={incomeQuintiles}
              onChange={setIncomeQuintiles}
            />
            <Choice
              label="Q3"
              value={3}
              chosen={incomeQuintiles}
              onChange={setIncomeQuintiles}
            />
            <Choice
              label="Q4"
              value={4}
              chosen={incomeQuintiles}
              onChange={setIncomeQuintiles}
            />
            <Choice
              label="Q5 (highest)"
              value={5}
              chosen={incomeQuintiles}
              onChange={setIncomeQuintiles}
            />
          </div>
        </fieldset>
        <Field
          label="What are they like? (optional)"
          value={audience}
          onChange={setAudience}
          placeholder="night-shift workers who commute by car"
          multiline
          // Mirrors MAX_AUDIENCE_CHARS (schemas.py); the backend refuses longer.
          maxLength={200}
        />
        <Field
          label="Headline A"
          value={headlineA}
          onChange={setHeadlineA}
          placeholder="Save 50% this week"
        />
        <Field
          label="Headline B"
          value={headlineB}
          onChange={setHeadlineB}
          placeholder="Members save half price this week"
        />
        <button
          type="submit"
          disabled={disabled}
          className="rounded bg-ink px-4 py-2 text-surface disabled:bg-surface-2 disabled:text-ink-3"
        >
          {state.phase === "loading" ? "Asking the panel…" : "Evaluate"}
        </button>
        {/* Submitting counts as interacting with an AI system, so the
            disclosure sits with the submit control rather than in a footer —
            told before the exchange, where the telling can still change it. */}
        <p className="text-xs text-ink-2">{AI_SYSTEM_DISCLOSURE}</p>
        {/* Only when this deployment is really tracing — the backend's own
            answer, not a second flag here that could disagree with it. A
            deterrent, not a control: the controls are the screener and the
            limits. */}
        {tracing && (
          <p className="text-xs text-ink-2">
            Runs are traced for debugging: what you type — your audience, both
            headlines, and anything you later ask the analyst — is sent to
            LangSmith, outside our infrastructure. Don&rsquo;t paste anything
            unreleased.
          </p>
        )}
      </form>

      {state.phase === "loading" && <Waiting />}

      {state.phase === "error" && (
        <p className="text-red">Error: {state.message}</p>
      )}

      {/* On the form and on the report, and deliberately not at the gate: the
          gate is a decision about spending money, and a list of other tests
          beside it is an invitation to leave it half-answered. */}
      <PastTests onOpen={show} />
    </div>
  );
}
