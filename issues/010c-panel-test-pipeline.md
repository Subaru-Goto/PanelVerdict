---
title: "The panel-test pipeline: target description in, verdict out"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: []
assignee: Subaru-Goto
status: closed
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

**The panel size** — now a config profile, not a constant this ticket picks.
`settings.panel.size` is declared and unread until this ticket consumes it, the same status
`settings.targeting_model` has.

- [007](007-build-targeting-query-translation.md) asks for **100–300 personas**, all
  target-matched.
- `dev` 25 · `demo` 100 · `prod` 200, defaulting to `dev` so an unconfigured run costs a
  cent rather than a tenth of the credit cap. Resolutions and costs are in `config.py`.
- **The reason for 200 changed on 2026-07-28, while the number stayed.** It had been chosen
  so `practical_tie` would be reachable at the ±7 ROPE; a tie is in fact reported on only
  **~5.6%** of genuinely tied panels at that size, so that reason never held. What justifies
  200 is its **resolution**: it calls a ±14-point gap decisive, for $0.107 a run.
- Sizing is not fixed forever: deriving n from the resolution a customer asks for is
  [019](019-derive-panel-size-from-resolution.md), a v2 ticket.

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

## Closed 2026-07-28

`app/pipeline.py::run_panel_test` — the straight line, with the HTTP layer mapping its two
refusals: an **empty panel is 422** (the target names an audience this pool cannot serve;
nothing was spent, and the model is never constructed), a **panel with zero votes is 502**
(the provider failed; the message carries exception types only). A partial run returns 200
with the shortfall visible in the counts — no threshold invented, per this ticket;
[010b](010b-partial-run-threshold.md) still owns that line. `FIXED_PANEL` is out of the
product path; `/evaluate` now requires `target_description` and returns counts, the query
(with `coverage` as data) and the full notice set.

Deviations and corrections:

1. **The pgvector requirement above was stale, and the connection design collapsed with
   it.** `retrieve_panel` selects scalar columns only — [017](017-representative-sampling.md)
   removed the persona vector from this path after this ticket was written — so there is no
   pool, no `configure=` hook, and no adapter: one plain `psycopg.connect` per request.
   `register_vector` remains the write path's and [012](012-build-analyst-chatbot-tools.md)'s
   concern.
2. **`test_id` is a uuid4 correlation id only.** There is no `tests` table until
   [010e](010e-per-vote-cache.md); it ties one run's log lines and vote records together.
3. **The frontend is deliberately broken until [011](011-build-report-ui.md).** The form
   does not send `target_description` yet; accepted rather than patched minimally twice.

**The first paid run through this pipeline happened by accident, and its exact cost is
unrecoverable** — a validation script turned out to run against live credentials and the
seeded dev pool: 25 votes + 1 translation, ~$0.014 *derived* from the 010a rate, because the
bare script never configured logging and the INFO usage line was dropped. The failure this
section warned about, demonstrated on its own ticket. Two consequences: uvicorn configures
logging in real deployments, but any bare script driving the pipeline must call
`logging.basicConfig` first; and the **deliberate** first 200-vote run — which supersedes
010a's 10-persona reading and supplies the latency distribution
[010f](010f-budget-guard.md) wants — is still to be done, $0.107 at prod size. One free
observation from the accidental payload: with literal headlines "a"/"b", 23/25 personas
chose 'a', mostly reasoning "first letter of the alphabet" — 014's position/content bias,
live.

`FIXED_PANEL` itself survives in `app/panel.py` referenced only by its own test —
dead weight to sweep in a later cleanup, not product path.

412 tests green (+11), ruff check and format clean.
