---
title: "A slow run leaves no evidence: per-vote seconds are measured, then dropped"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found 2026-07-30, trying and failing to answer a real question)

"Why is it so slow?" — asked about a `dev` run, 25 panelists — could not be
answered. Not because the answer is hard, but because **the run keeps no
record of its own time.**

`VoteUsage` measures `seconds` per vote, locally, precisely because no provider
reports it (`vote.py:36-40`). `total_usage` then sums input tokens, cached
tokens, output tokens, reasoning tokens and cost — and drops `seconds` on the
floor. `UsageTotals` has no time field at all, so the single line a run logs
(`pipeline.py:305`) says what the run *cost* and nothing about what it *took*.

The consequence is not academic. Every explanation offered for the slow run was
inference from constants — `VOTE_CONCURRENCY`, the read timeout, the p99 in
`docs/research/first-full-scale-run.md` — and one of them was simply wrong
(sequential waves, which do not exist at `dev`'s 25). Guessing was the only
option available.

## Fix

Three numbers, none of them derivable from the others:

- **`seconds_slowest`** — a wave finishes with its slowest member, so this is
  what a run's wall time is actually made of.
- **`seconds_total`** — beside it, how much of that work happened at once. The
  ratio to wall time is the effective concurrency.
- **`wall=` on the log line** — the run's own clock. Votes fan out, so their
  seconds do not add up to the run's, and no per-vote figure can supply this.

Together they separate the two hypotheses that look identical from outside: one
straggler holding its wave (slowest ≈ wall, total low) versus everything being
slow at once (total ≈ slowest × votes).

`default=0.0` on the slowest rather than a guard: a run of pure cache hits
waited on no model, and zero is the honest answer, not a missing figure.

## Why this before the fix

[032](032-slow-run-is-visible.md) was started first — a client deadline and a
stated expectation — and parked half-built. It is a real ticket, but it dresses
a symptom: it would have made the wait *legible* without making it
*explicable*, and the cause would still be unknown. Evidence first.

## What this is expected to settle

**`reasoning_effort` is never set in production.** Fully plumbed
(`llm.py:220`, `llm.py:273`), with its own closed vocabulary (`llm.py:32`), and
the only caller passing a value is a test. `get_panel_llm` (`main.py:54-59`)
omits it, so every vote runs at gpt-5-mini's default effort. `reasoning_tokens`
is already in this log line — so the first instrumented run says how much of
the time and bill that is, and turns a plausible story into a measurement.

It stays unset until then, and changing it is its own ticket regardless: effort
is part of the vote fingerprint (`llm.py:236-242`), so it invalidates every
cached vote, and [015](015-task-framing-sensitivity.md) showed the verdict moves
when the ask moves.

## Related

- [032](032-slow-run-is-visible.md) — the parked half: deadline and expectation.
- [010a](010a-vote-usage-instrumentation.md) — measured `seconds` in the first
  place; this finishes the job by aggregating it.
- `docs/research/first-full-scale-run.md` — p50 6.5s, p99 14.0s, slowest 18.9s,
  the numbers any new measurement gets compared against.
