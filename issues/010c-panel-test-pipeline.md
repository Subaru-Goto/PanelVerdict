---
title: "The panel-test pipeline: target description in, verdict out"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: []
assignee: null
status: open
---

## Goal

One function, plain Python, replacing the tracer bullet:

```
target description + two headlines
  → resolve_target / select_panel  (007, 017)
  → collect_panel_votes            (008)
  → tally_votes / panel_verdict    (009)
  → a payload the report can render (011)
```

Then wire `/evaluate` to it and retire `FIXED_PANEL` from the product path.

**No adaptive stopping here** — one full panel, one posterior.
[010d](010d-adaptive-stopping.md) adds the loop, and keeping them apart means the first
end-to-end run is a straight line that either works or does not.

## What this ticket owns

**The panel size.** `select_panel(size=...)` accepts any size ≥ 1 on purpose — it is a
mechanism, and a retrieval function that refused small draws would block the tests and any
segment-vs-segment comparison. So the policy lands here:

- [007](007-build-targeting-query-translation.md) asks for **100–300 personas**, all
  target-matched.
- **n=200 is the signed-off default** (2026-07-27), chosen so `practical_tie` is reachable
  at the ±7 ROPE ([009](009-build-bayesian-layer.md)).

**Three counts in the payload — requested, matched, voted.** The verdict rests on the third
(`len(votes.records)`), and all three have to reach the report or
[011](011-build-report-ui.md) cannot tell the reader what the verdict is a verdict *on*.
Emitting the counts is this ticket's; deciding when they make a run **partial** is
[010b](010b-partial-run-threshold.md)'s. If 010b has not landed yet, report the counts and
offer the verdict — do not invent a threshold in passing.

**Carrying the notices through.** `PanelSelection.notices` holds the coverage warnings and
the trait readings, and `TargetQuery.coverage` distinguishes *"you asked for everywhere"*
from *"we could not serve where you asked"* — two cases with an identical country tuple. The
payload must carry `coverage` as data, not just the country list, and the notices must not
be dropped in assembly.

**The DB dependency `/evaluate` does not have yet.** The endpoint currently votes an
in-memory panel; retrieval needs a connection with the pgvector adapter registered. Follow
`prepare_connection`'s split noted in [012](012-build-analyst-chatbot-tools.md): if a
connection pool is used, register the vector adapter per checkout via `configure=`, **not**
`prepare_connection`, which also runs DDL and must not fire on every checkout.

**`settings.targeting_model`** is declared and unread until this ticket constructs
`OpenRouterTargetTranslator`.

## Cost, and the one ordering constraint

A full run is 200 vote calls plus one translation. Do **not** let the first 200-vote run
happen before [010a](010a-vote-usage-instrumentation.md) lands — a run without usage logging
is a run whose cost is unrecoverable, and this is the ticket that will produce the first one.
Developing against a stub or a 5-persona panel is free; the real run is the thing to hold.

When the first real 200-vote run does happen, it supersedes 010a's 10-persona reading: record
the actual per-test cost and the latency distribution.

## Not in scope

- The stopping loop → [010d](010d-adaptive-stopping.md).
- Vote caching and resume → [010e](010e-per-vote-cache.md).
- Budget pre-flight, 402 handling, read timeout → [010f](010f-budget-guard.md).
- The partial-run rule → [010b](010b-partial-run-threshold.md).
- Gap-fill persona generation is **fog** (see map Notes) — do not build it unless the
  frontier has graduated it.
- Segment breakdown target vs. control: dropped 2026-07-26. A production panel is one target
  group and the posterior is read off it; controls live in the testing track.
