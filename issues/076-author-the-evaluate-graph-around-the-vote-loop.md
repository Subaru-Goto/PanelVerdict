---
title: "Author the evaluate graph around the vote loop — screen → select → confirm → vote → assemble"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: [046-analyst-threads-die-on-restart]
assignee: null
status: open
---

## Goal

`/evaluate` runs as a hand-authored LangGraph `StateGraph` whose nodes are today's
pipeline stages, pausing at a `confirm` node with `interrupt()` so a human approves or
redraws the panel **before any vote is bought** — while the vote loop itself (chunked
concurrency, adaptive stopping, the ledger) stays inside one node, unchanged.

This is [067](067-where-is-a-hand-authored-graph-worth-it.md)'s middle path, decided
2026-08-21, and it carries [054](054-nothing-confirms-the-panel-before-the-money-is-spent.md)'s
spend gate in its final form — one graph with an interrupt, replacing 054's provisional
two-endpoint recommendation exactly as map 055's fog note predicted.

## Topology

```
START → screen → select → confirm ──(accept)──→ vote → assemble → END
                   ↑          │
                   └(redraw)──┘         interrupt() at confirm
```

- **screen**: today's `screening.py` call — before anything else, as now.
- **select**: `select_panel` unchanged. `EmptyPanel` surfaces here, which moves the 422
  earlier in the reader's experience — the straight improvement 054 already argued.
- **confirm**: `interrupt()` carrying what 054 showed is already computed before money
  moves: the resolved `TargetQuery`, matched count, notices, and the existing
  `size × USD_PER_VOTE` estimate — **plus the panel's composition** (age spread, country,
  gender, education, income bands; the same aggregation shape
  [025](025-analyst-panel-composition-facts.md) built for `analyze_results`, computed here
  from the selected personas rather than from votes). Resume value is `accept` or
  `redraw`; a conditional edge routes accordingly.
- **redraw** loops back to `select`: selection is SQL-only and free, and since
  [017](017-representative-sampling.md) the seed varies every draw, a redraw is a fresh
  uniform sample under the *same* filter — the interpretation stays fixed; only the draw
  changes.
- **vote**: `collect_panel_votes` unchanged, `ThreadPoolExecutor` and all, inside one
  node. The chunk loop, adaptive stopping, `OutOfCredit` handling, and the ledger do not
  move — 010e's byte-identical replay guarantee is a documented dependency of the $0 demo
  ([061](061-a-zero-cost-demo-page.md)) and this ticket must not touch it.
- **assemble**: tally + verdict + notices, as today.

## What this depends on and why

- **Blocked by [046](046-analyst-threads-die-on-restart.md):** `interrupt()` persists the
  paused run in a checkpointer, so a pause that dies on restart/deploy is worse than no
  gate. 046 delivers `PostgresSaver`, the long-lived connection lifecycle, and the DDL-
  ownership answer this graph reuses.
- The wire contract changes: `/evaluate` becomes start + resume (thread id travels to the
  client between them). Frontend consumption is
  [077](077-panel-preview-accept-or-redraw.md)'s.
- Sync stays sync: the graph nodes call today's synchronous functions; no `llm.py`
  call-site rewrite. That is the point of the middle path.

## Decisions to record while building (not to settle by silence)

- Where the pending run's expiry lives — a paused, never-resumed run is the first
  *pending* state this system has had; 054 deferred persistence questions to the `tests`
  table era ([060](060-nothing-persists-a-finished-test.md)).
- Whether `redraw` is bounded. Redraw-shopping cannot shop the verdict (no votes exist
  yet), but an unbounded loop is still worth a recorded position — even if the position
  is "unbounded, because selection is free and the filter is fixed."
- Per-stage LangSmith spans arrive free with named nodes once
  [065](065-langsmith-behind-a-flag.md) lands — note it in the trace review, don't build
  for it.

## Done when

A run pauses after selection with the panel visible and priced, resumes on accept into
paid votes, redraws freely under the same filter, survives a process restart while
paused, and the vote loop's tests pass untouched — with the replay guarantee
demonstrably intact (a re-run of a finished test still replays byte-identical for $0).
