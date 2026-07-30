---
title: "The report is unreadable in the order it presents itself: form on top, 25 raw reasons below"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [029-serve-vote-reasons-to-the-analyst]
assignee: null
status: open
---

## Problem (found in real use, 2026-07-30)

Three complaints, one cause — the page never stops being a form and never
starts being a document.

1. **The form stays above the report.** `evaluate-form.tsx` renders `<form>`
   unconditionally and `{state.phase === "done" && <Report/>}` beneath it, so
   the reader scrolls past the inputs to reach the answer, every time.
2. **Twenty-five reasons are too many to read.** `VoteList` prints every vote
   in full, so the most interesting thing the panel produced is also the least
   readable, and it sits at the bottom where a reader arrives already tired.
3. **Nothing summarises them.** A summary of prose is a model job — themes
   live in words, and no arithmetic over 25 free-text reasons yields "the ones
   who picked B said it felt earned". [029](029-serve-vote-reasons-to-the-analyst.md)
   built the door; this ticket walks through it.

## Fix

- **Test again** replaces the form once a report exists. The inputs stay in
  state, so returning lands on a filled form ready to be tweaked rather than a
  blank one to be retyped — the common case is changing one headline.
- **A summary card above the panelists**, streamed from the analyst as turn 1
  of the dock's own thread. One extra paid call per test.
- **The panelist list collapses** into `<details>`, closed by default, reusing
  the disclosure already at `report.tsx:213`. Detail is a click away rather
  than a scroll past.

## Why the summary shares the dock's thread

Not tidiness — context. A separate call would leave the dock opening cold on a
report the analyst has already read, so the reader's first follow-up buys the
same tool calls a second time. As turn 1 the summary *is* the conversation's
opening, and "which of them said that?" resolves against words already in the
transcript.

Consequence to build for: `useAnalyst` currently lives inside `AnalystDock`.
It has to lift into `Report` so the card and the dock share one hook, one
thread, one `busy`.

## The caveat must not collapse with the list

"Reasons from synthetic panelists — sampled personas, not real people" sits
above the votes today. Collapsing the list would hide it, and a *summary* of
synthetic opinions needs that line more than the raw list does — the summary
reads like a finding, which is exactly when a reader forgets the panel is
synthetic. It moves onto the card.

## Auto-send needs a guard the suite can see

The effect that opens the conversation fires twice under Strict Mode, which is
what dev always runs ([027](027-dock-frozen-in-dev.md)). `send`'s existing
`busyRef` swallows the second call by luck of ordering rather than by design;
this needs a guard that survives the remount and a test that renders through
`StrictMode`, as the dock suite now does.

## Honest limit

The summary is a model's prose about a corpus, so its faithfulness is
unassertable — the same judge-territory boundary as 025's and 026's prompt
halves. What ships tested is that the conversation opens exactly once, that
its answer renders above the panelists, and that the dock shares the thread.

## Related

- [029](029-serve-vote-reasons-to-the-analyst.md) — the tool this consumes.
- [011](011-build-report-ui.md) — the cold-reader standard this serves.
