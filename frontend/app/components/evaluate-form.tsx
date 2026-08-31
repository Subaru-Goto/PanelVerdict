"use client";

import { useRouter, useSearchParams } from "next/navigation";
import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type SubmitEvent,
} from "react";

import {
  LOCALES,
  MAX_PANEL_AGE,
  MIN_PANEL_AGE,
  myTest,
  type EducationLevel,
  type EvaluateInput,
  type Gender,
  type Locale,
} from "../lib/api";
import { AI_SYSTEM_DISCLOSURE } from "../lib/disclosure";
import { onAuthChange, signInAvailable } from "../lib/auth";
import SignInSheet from "./sign-in-sheet";
import { useEvaluate } from "../lib/use-evaluate";
import PanelGate from "./panel-gate";
import Report from "./report";
import { COUNTRY_LABELS, readingKey, readingSummary } from "../lib/reading";
import { useGateSignal } from "./shell";
import Stepper, { type StepName } from "./stepper";

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
  const {
    state,
    submit,
    answerGate,
    reset,
    show,
    fail,
    adjustAudience,
    accepted,
    forgetReading,
  } = useEvaluate();

  // The frame puts the rail away while the gate is open (#252) — the page is
  // the only thing that knows which phase it is in.
  useGateSignal(state.phase === "gated");

  // The form itself is behind Google (prototype, 2026-08-25): the backend
  // refuses unsigned runs, so a form a signed-out visitor could fill in would
  // be a promise the submit cannot keep. null until the session is known — a
  // wall must not flash at a reader who turns out to be signed in. A build
  // with no identity provider at all keeps the form: a wall nothing can open
  // would make the app undevelopable (the sign-in control's own rule).
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const authGated = signInAvailable();
  useEffect(
    () =>
      onAuthChange((value) => {
        setSignedIn(value);
        if (value) setSheetOpen(false);
      }),
    [],
  );

  // The wizard learns which stored test to show from its address (119/#257):
  // the rail lives in the shell and a row is a link to `/test?open=<id>`, so
  // reopening works from any page the rail shows on. `live` guards the late
  // answer — a second link clicked before the first resolves must win.
  const router = useRouter();
  const openId = useSearchParams().get("open");
  // The rail's rows and "New test" are links into this same route, so Next
  // reuses the mounted page and only the params change. The previous id is
  // what tells "never had one" apart from "just lost one" — the second is
  // "New test" clicked from a reopened report, and means back to the form.
  const previousOpenId = useRef<string | null>(null);
  useEffect(() => {
    const wasOpen = previousOpenId.current !== null;
    previousOpenId.current = openId;
    if (openId === null) {
      if (wasOpen) reset();
      return;
    }
    let live = true;
    myTest(openId).then(
      (result) => {
        if (live) show(result);
      },
      () => {
        // Stale — deleted in another tab — or the fetch just failed. Either
        // way it must say so: a wordless fall to the blank form reads as data
        // loss. The address keeps the id, so a reload retries.
        if (live)
          fail("That test could not be opened — it may have been deleted.");
      },
    );
    return () => {
      live = false;
    };
    // `show`, `reset` and `fail` are stable for the component's life; the id
    // is the input that means anything.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openId]);

  // Leaving the report must also leave its address, or a reload would bring
  // the abandoned report straight back.
  function startOver(): void {
    if (openId !== null) router.replace("/test");
    reset();
  }

  const request: EvaluateInput = {
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
  };

  function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit(request);
  }

  // The approval stands for exactly one reading; the echo shows only while
  // the form still describes it. Edit a control and the line withdraws on its
  // own — the next submit gates again, which is what the reader just asked.
  const standing =
    accepted !== null && readingKey(request) === accepted.key ? accepted : null;

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

  // What the phase puts above the rail. The rail itself stays outside this
  // switch: its rows change when a run finishes or the session changes, not
  // when the page turns — rendered inside each branch it remounted on every
  // transition, and every mount refetched (118/#253).
  if (authGated && signedIn !== true) {
    if (signedIn === null) return null;
    return (
      <div className="flex flex-col items-start gap-4">
        <h2>Two versions, one panel.</h2>
        <p className="text-ink-2">
          Running a test costs money, so it asks who you are.
        </p>
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          className="rounded-pill bg-ink px-6 py-3 font-medium text-surface"
        >
          Sign in to run a test
        </button>
        {sheetOpen && <SignInSheet onClose={() => setSheetOpen(false)} />}
      </div>
    );
  }

  // The step is the phase wearing its name: the audience is being read from
  // the moment the form is sent until the gate is answered, and the votes are
  // being bought from that answer until the report exists.
  const step: StepName =
    state.phase === "done"
      ? "Verdict"
      : state.phase === "gated" && state.resuming
        ? "Voting"
        : state.phase === "gated" || state.phase === "loading"
          ? "Audience"
          : "Copy";

  let main: ReactNode;

  // Once a report exists the page stops being a form: the reader wants the
  // answer at the top rather than the inputs they already filled in.
  if (state.phase === "done") {
    main = (
      <>
        <button
          type="button"
          onClick={startOver}
          className="self-start rounded border border-line px-3 py-1.5 text-sm"
        >
          Test again
        </button>
        {/* Keyed, so a report replacing another *without* leaving this phase
            gets its own analyst. Reopening from the rail below does exactly
            that, and unkeyed it inherited the previous report's chat thread and
            transcript — see the epoch's comment in use-evaluate. */}
        <Report key={state.epoch} result={state.result} />
      </>
    );
  }

  // Holding at the gate: the reader decides whether to buy the votes.
  else if (state.phase === "gated") {
    main = (
      <div className="flex flex-col gap-4">
        <PanelGate
          preview={state.preview}
          // The words as submitted — while the gate is up the form is away,
          // so this state still reads exactly what the run was asked with.
          audience={audience}
          notice={state.notice ?? null}
          // Returned, not voided: the gate re-arms its button when this
          // settles, and a swallowed promise would re-arm it mid-spend.
          onAccept={(instruction) =>
            answerGate("accept", undefined, instruction)
          }
          onBack={adjustAudience}
        />
        {state.resuming && <Waiting />}
      </div>
    );
  } else {
    main = (
      <>
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
                  label={COUNTRY_LABELS[code]}
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
          {standing !== null && (
            <p className="flex items-center gap-2 text-xs text-ink-2">
              <span>
                Read as: {readingSummary(standing.preview)} — approved, so the
                next run will not stop to ask again.
              </span>
              <button
                type="button"
                onClick={forgetReading}
                className="underline underline-offset-2"
              >
                Change
              </button>
            </p>
          )}
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
      </>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {state.phase === "idle" && <h2>Two versions, one panel.</h2>}
      {state.phase === "gated" && !state.resuming && (
        <h2>How your audience was read.</h2>
      )}
      <Stepper current={step} />
      {main}
    </div>
  );
}
