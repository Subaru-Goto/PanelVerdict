---
title: "Progress UX: replay animation and/or live SSE streaming (v2)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [011-build-report-ui]
assignee: null
status: open
---

## Question

A prod run is 4–6 minutes of waiting. How should the customer see progress — and is
the answer a replay after the fact, a live stream, or both?

Deferred from [011](011-build-report-ui.md) to v2, decided with the user 2026-07-28.
011 ships with a plain pending state; this ticket owns everything beyond it.

## The two fidelity levels

- **Replay animation** (frontend-only): the ordered vote records already re-derive
  the 25-vote chunks ([010d](010d-adaptive-stopping.md) noted this when it deleted
  `Batch`), so the narrowing-posterior animation can play back after the response
  lands. No backend change; no live information.
- **Live SSE** (backend work): `run_panel_test` is a synchronous function behind one
  blocking POST. Streaming "87/200 voted…" means restructuring the chunk loop to
  yield, a new SSE endpoint, and a run-identity story (the vote cache's fingerprints
  may help here — a run is resumable, so a progress stream that drops can be
  re-attached by re-running).

The replay is a strict subset of the work and can ship first even inside this ticket.

## Constraint carried over

However progress is shown, an early stop must read as an answer, not an interruption
— the stopped-early notice's framing ("the rest went unasked") applies to the
animation's final frame too.
