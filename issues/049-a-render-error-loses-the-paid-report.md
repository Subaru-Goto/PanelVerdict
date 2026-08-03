---
title: "A render error loses the report the customer just paid for"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The gap (sprint review feedback, 2026-08-03)

> *"A rendering error in `Report` or `AnalystDock` … would crash the entire page with
> React's default error screen — no recovery, no user-facing message. … A crash loses
> the report the user just paid for."*

Correct, and the cost is exact: a `prod` run is **$0.145** and up to 200 model calls.
A `TypeError` in a formatter throws all of it away and shows a blank screen.

## Why this is plausible rather than theoretical

[048](048-no-test-takes-the-path-a-user-takes.md) found the mechanism.
`api.ts:162` is:

```ts
return (await res.json()) as EvaluateResponse;
```

An **unchecked cast**. Nothing validates the payload at the boundary, so a shape
mismatch is not caught at the fetch — it survives into render and fails there, deep
inside a formatter. 048 is the *detection* of that class of defect; this ticket is the
*containment*. Neither replaces the other: a test cannot catch a payload no test
imagined, and a boundary cannot tell you the contract drifted.

## The good news: the paid payload is still in memory

`EvaluateForm` holds it — `state.result`, rendered at `evaluate-form.tsx:109`. So when
`Report` throws, the response is **still there**, one component up. A fallback can show
it without re-fetching and without re-paying. That is what makes the reviewer's
suggested fix — render the raw JSON — actually reachable rather than aspirational.

Raw JSON is also the right fallback rather than a lazy one:

- it preserves the artifact that cost money, which a friendly *"something went
  wrong"* discards
- it is copy-pasteable, so the user's bug report contains the payload that broke it

## This Next.js is 16.2.10, and the API is not what you remember

Read from `node_modules/next/dist/docs/01-app/01-getting-started/10-error-handling.md`
rather than recalled, per the standing warning in `frontend/AGENTS.md`. Two things
would trip an implementation written from memory:

- **The signature is `{ error, unstable_retry }`, not `{ error, reset }`.** Writing
  `reset` gives you `undefined` and a dead button, with no type error if it is
  destructured loosely.
- **There is a component-level boundary**, `unstable_catchError as catchError` from
  `next/error`, which returns a wrapper usable around arbitrary children.

## `error.tsx` is the wrong tool here, and that is the design decision

The obvious move is a route-segment `error.tsx`. It fails this ticket's own goal:

- the whole app is **one route** — `page.tsx` → `EvaluateForm` → `Report`
- a segment boundary therefore replaces the **entire page**, taking the *"Test again"*
  button with it
- so the user is left with neither the report nor a way to re-run — strictly worse than
  the crash it replaced, because it looks handled

**Use the component-level `catchError` wrapper instead**, around `<Report>` where it is
rendered. The form, the button and the page chrome survive; only the broken subtree is
replaced.

**And wrap the dock separately.** `AnalystDock` renders *inside* `Report`
(`report.tsx:341`), so one boundary around `Report` means a dock error blanks the
verdict too. They fail for unrelated reasons and only one of them is the paid artifact,
so the report should survive a dock crash. Two boundaries, nested.

## What a boundary does not cover

The docs are explicit: *"Error boundaries don't catch errors inside event handlers.
They're designed to catch errors during rendering."*

So this protects **render**, not the stream — and the stream does not need it.
`use-analyst.ts` already models streaming failure in-band as `error: string | null`
per turn, and `stream_analyst` sends a fixed sentence as an `error` event rather than
throwing. That channel is already correct; nothing here should touch it.

## Testable, unlike most of the analyst work

Worth stating because it is unusual in this project: a boundary is straightforwardly
testable. `__tests__/` already holds `report.test.tsx` and `analyst-dock.test.tsx`, so
the test is *render a child that throws, assert the fallback appears and the payload is
in it* — and the sibling assertion that matters as much, that a dock error leaves the
verdict on screen.

## Done when

A throw inside `Report` shows the response JSON with the page and *"Test again"* still
usable, a throw inside `AnalystDock` leaves the verdict intact, and both are pinned by
tests — so the response that cost $0.145 cannot be destroyed by a formatter.
