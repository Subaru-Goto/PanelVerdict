---
title: "The panel preview: a reader sees who was seated — and accepts or redraws — before paying"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: [076-author-the-evaluate-graph-around-the-vote-loop]
assignee: null
status: open
---

## Goal

After submitting headlines and a target, the reader sees the audience the system
understood and the panel it seated — the resolved filter, the matched count, the
composition distributions (age, country, gender, education, income band), the notices,
and the cost estimate — then chooses **accept** (votes are bought) or **redraw** (a fresh
free sample under the same filter). Author's direction, 2026-08-21.

## Scope

- A preview step between the form and the report, consuming
  [076](076-author-the-evaluate-graph-around-the-vote-loop.md)'s interrupt payload and
  resuming with one of **three** actions (`accept` / `adjust` / `redraw`).
- **Adjust — the resolved filter is editable** (author's direction, 2026-08-21,
  superseding 054's exclusion): redraw fixes a bad *draw*, but only editing fixes a bad
  *reading* — if "young professionals" resolved to 18–65, every redraw samples the same
  wrong filter. The resolved `TargetQuery` renders as structured controls (age bounds,
  countries, education/income bands, trait levels); each **inferred** reading's notice
  (the 024/037/038 disclosure arc) renders beside the control it explains, so what was
  guessed sits exactly where it can be overridden. Editing is free and deterministic —
  pure SQL re-selection, never a second translation call (which is paid,
  non-reproducible, and once cost $0.13 — the re-translate-on-edit trap 054 already
  named).
- Distributions rendered in the trait-chip / demographic vocabulary the report already
  speaks ([023](023-vote-feed-voter-details.md)) — same words before and after the money,
  so the preview and the report corroborate each other by inspection.
- The disclosure discipline carries over: notices (unmappable phrases, inferred readings
  from [024](024-fuzzy-age-words-in-targeting.md)/[037](037-income-reading-is-never-disclosed.md)/[038](038-education-reading-is-never-disclosed.md))
  appear *here*, where they can still change the decision — not only on the report after
  payment.
- Cost line uses the existing estimate; its accuracy is
  [070](070-what-does-a-run-actually-cost.md)'s to fix, not this ticket's to invent.
- New copy goes through cold-reader iteration, per the map's standing practice.

## Deliberately out of scope

- ~~Editing the resolved filter by hand~~ — 054 excluded it as "a larger feature and a
  different argument"; **the argument arrived** (author, 2026-08-21: resampling cannot
  fix a misreading) and it is now the `adjust` action above.
- Approval on anything past this gate (adaptive stopping, partial runs — automatic calls
  that save money or report honestly).
- Free-text *re-translation* from inside the preview — going back to the form and
  rephrasing stays the path for "I meant something else entirely".

## Done when

A mis-read target costs a click instead of ~$0.15 and a report about somebody else; a
reader can name who was seated before paying; a wrong inferred reading is fixable in
place without a second paid translation; redraw visibly reseats the panel without
re-typing anything; and the preview's vocabulary matches the report's.
