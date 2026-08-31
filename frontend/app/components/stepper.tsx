"use client";

/** The four-step chrome from the prototype (119/#257). Labels only — the
 *  steps are the run's phases wearing their names, so there is nothing to
 *  click: the run moves, the chrome follows.
 */
const STEPS = ["Copy", "Audience", "Voting", "Verdict"] as const;

export type StepName = (typeof STEPS)[number];

export default function Stepper({ current }: { current: StepName }) {
  return (
    <ol className="flex gap-8 border-b border-line pb-3 text-xs font-medium uppercase tracking-[0.18em]">
      {STEPS.map((step, index) => {
        const active = step === current;
        return (
          <li
            key={step}
            aria-current={active ? "step" : undefined}
            className={`flex items-center gap-2 ${active ? "text-ink" : "text-ink-3"}`}
          >
            <span
              aria-hidden="true"
              className={`flex h-5 w-5 items-center justify-center rounded-pill text-[11px] ${
                active ? "bg-ink text-surface" : "border border-line"
              }`}
            >
              {index + 1}
            </span>
            {step}
          </li>
        );
      })}
    </ol>
  );
}
