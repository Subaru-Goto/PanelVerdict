---
title: "A $0 demo page: fixed target, stored report, no translator call"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: [060-nothing-persists-a-finished-test]
assignee: null
status: open
---

## Goal

An ungated page where a visitor clicks once and sees a real report, costing nothing, so the
work is visible in seconds without a login wall.

**The saving is skipping translation, not caching votes.** That is the non-obvious part:
`select_panel` makes a model call, and `docs/research/targeting-call-effort.md` records one
costing **$0.13** — *"roughly a whole 200-vote panel run."* A demo that relied on the vote
cache alone would still pay for translation on every click. So the demo path uses a
**fixed, pre-resolved target** and never invokes the translator.

And it serves a **stored report** rather than replaying votes, because
[040](040-vote-cache-read-window.md)'s 24-hour read window means a vote-replay demo starts
charging a day after it is seeded. Depends on [060](060-nothing-persists-a-finished-test.md)
for the table.

Scope:

- a seeded report row, committed as a fixture so the demo survives a database reset
- a route that serves it with no screener call, no translator call, no votes
- the analyst **login-gated** on this page, per the map — with a line saying why, not a dead
  control
- honest copy about what the demo is: it runs the `dev` profile (25 votes) rather than `prod`
  (200), and the resolution differs — ±24 against ±13.9 points. The map's fog records that
  the wording is undecided; this ticket needs it decided.

Explicitly not: a fake report. Everything shown is a real run's real output, which is the
entire point.
