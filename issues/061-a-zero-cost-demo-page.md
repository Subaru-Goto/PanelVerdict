---
title: "A $0 demo page: fixed target, stored report, no translator call"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: [060-nothing-persists-a-finished-test]
assignee: null
status: open
---

## Goal

An ungated page where a visitor clicks once and sees a real report, so the work is visible in
seconds without a login wall.

**"$0" in the title means per visitor, and that is the property that matters** — unlimited
people can read a real 200-vote report and the meter never moves. Seeding it is not free:
two or three real `prod` runs cost about **$0.18 once, ever** (estimated at the current
per-vote figure; it was $0.44 when the panel ran gpt-5-mini), against
[064](064-the-cost-ceilings.md)'s $1.00 daily ceiling. A one-time spend, not a per-view one.

**The saving is skipping translation, not caching votes.** That is the non-obvious part:
`select_panel` makes a model call, and `docs/research/targeting-call-effort.md` records one
costing **$0.13** — *"roughly a whole 200-vote panel run."* A demo that relied on the vote
cache alone would still pay for translation on every click. So the demo path uses a
**fixed, pre-resolved target** and never invokes the translator.

And it serves a **stored report** rather than replaying votes, because
[040](040-vote-cache-read-window.md)'s 24-hour read window means a vote-replay demo starts
charging a day after it is seeded. Depends on [060](060-nothing-persists-a-finished-test.md)
for the table.

## Amended 2026-08-04: two or three configs, chosen to show the three verdicts

Not variety for its own sake — **each stored report should show a different verdict**, because
that is what teaches a visitor what the product is. `verdict.py:279-284` says the third
outcome *"is the point of the method"*:

| config | verdict | what it demonstrates |
|---|---|---|
| 1 | `decisive` | a winner called, the interval clear of the band |
| 2 | `undecided` | a lean is not a result — and `detectable_gap` makes the null readable |
| 3 | `practical_tie` | **credibly too small to matter** — a *positive* finding "not significant" can never state |

A single `decisive` example looks like any A/B tool. Clicking through all three shows the
method.

**Cost: about $0.18, once, ever** — three real `prod` runs at ~$0.060 each, estimated. Well under
[064](064-the-cost-ceilings.md)'s $1.00 daily ceiling, spent one time.

**The constraint that may bite.** [020](020-probability-not-label.md) records that a
`practical_tie` needs the interval **wholly inside** the band, which is only ~5.6% of splits at
n=200 — and [015](015-task-framing-sensitivity.md) found the panel prefers a variant even on
same-meaning copy. So a genuine tie may be hard to produce. **If it is, ship two and say so.**
Manufacturing one would be the fake report this ticket forbids.

Scope:

- two or three seeded report rows, committed as fixtures so the demo survives a database reset
- a route that serves it with no screener call, no translator call, no votes
- the analyst **login-gated** on this page, per the map — with a line saying why, not a dead
  control
- honest copy about what the demo is: **a real, previously-run `prod` panel** — 200 votes, the
  same size a paid run gets, replayed from storage rather than re-bought. **The disclosure
  question this bullet used to carry is gone**: an earlier draft had the demo on the `dev`
  profile and needed copy explaining a ±24 resolution against `prod`'s ±13.9.
  [064](064-the-cost-ceilings.md) put public paid runs on `prod` too, so there is no smaller
  panel to apologise for. What still needs saying is that the report is **replayed, not freshly
  run** — a visitor should not think their click bought 200 votes.

Explicitly not: a fake report. Everything shown is a real run's real output, which is the
entire point.
