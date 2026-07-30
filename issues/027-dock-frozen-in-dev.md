---
title: "The dock freezes on the first click in dev: a cleanup-only effect leaves `goneRef` stuck true"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found in real use, 2026-07-30)

Clicking a suggestion chip does nothing. Every chip, the composer input and
Send all render `disabled`, no text ever appears, and the dock stays frozen
for the life of the page. A regression from [012c](012-build-analyst-chatbot-tools.md)'s
dock UX work, live in dev the whole time.

## Cause

`use-analyst.ts` guards every paint and the end of `send` on `goneRef`, whose
only writer was an effect **cleanup**:

```ts
useEffect(() => () => { goneRef.current = true; ... }, []);
```

Refs are not re-initialised across React's dev-only
**mount → cleanup → mount**, and `useRef(false)` returns the existing ref on
re-render — so the simulated unmount sets the flag and nothing ever clears it.
Next's App Router turns Strict Mode on by default (confirmed in the installed
docs: *"Since Next.js 13.5.1, Strict Mode is `true` by default with `app`
router"*), so this is every dev page load.

Downstream, with the flag stuck true: `paint()` returns early so nothing
renders, the stream loop `break`s on its first event, and — the visible
symptom — `if (!goneRef.current) setBusy(false)` never runs, so `busy` stays
true forever and disables all three chips, the input and Send.

## Fix

Set `goneRef.current = false` in the effect **setup**, so every mount re-arms
it. One line; the cleanup keeps its real job of stopping a stream when the
dock genuinely unmounts mid-answer (a new evaluate).

## The suite's blind spot, and why it stays fixed

All nine dock tests called `render(<AnalystDock/>)` with no wrapper, so they
exercised a mount sequence **the dev server never performs** — the suite was
green against a dock that was frozen in every browser. The tests now render
through `StrictMode` by default, which is what dev does; verified by reverting
the one-line fix and watching all nine fail.

Worth keeping beyond this ticket: **a test harness that mounts differently
from the runtime is not testing the runtime.** Same shape as 025's finding
that `ScriptedChatModel` picks the tool on the model's behalf — in both cases
the double was quietly easier than reality.

## Related

- [012](012-build-analyst-chatbot-tools.md) — the dock, and the UX pass that
  introduced `goneRef`.
