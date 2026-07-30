---
title: "A slow run and a dead one look identical: no deadline, no expectation, no end"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found in real use, 2026-07-30)

"Why is it so slow until the report? I typed mid 30's male in the USA as a
target, it did not finish the evaluate process." The database was up.

The run was very likely not broken. It was doing exactly what the measured
numbers say it does — and nothing on screen could tell the reader that.

## Why it takes as long as it does — all of this is already measured

`docs/research/first-full-scale-run.md`, over 250 timed votes:

```
p50 6.5s   p95 11.1s   p99 14.0s   slowest 18.9s
```

Three things compound those per-vote seconds:

1. **A wave costs its slowest member.** `_chunk_votes` fans out through one
   `ThreadPoolExecutor` and the `with` block drains before anything continues,
   so a wave costs about p99 (14s), never p50.
2. **Waves are sequential, and how many depends on the profile.** `pipeline`
   chunks by `VOTE_CONCURRENCY = 25`, and adaptive stopping has to read the
   tally between chunks — the barrier is load-bearing, not an oversight. `dev`
   (25) is one wave; `demo` (100) is four; `prod` (200) is eight. The same
   research doc says it outright: the paid run takes **"minutes"**.
3. **A translator call comes first**, before a single vote is requested.

## The actual defect

`api.ts` calls `fetch` for `/evaluate` with **no `AbortSignal` and no
deadline**. A run that has died is indistinguishable from one that is working,
permanently: no error, no cutoff, a button that reads "Asking the panel…"
until the tab is closed. The product cannot tell its own user the difference
between working and broken.

Nothing tells the reader what to expect, either. A minute of silence is fine
if you were told it would take a minute.

## Fix

- **The client learns the run's size.** `/health` is the one call the page
  already makes on load, and the question it answers becomes "can I use this,
  and what will a run look like" — panel size is the only new field.
- **A deadline derived from published constants, not invented.** A vote's worst
  case is `VOTE_READ_TIMEOUT_SECONDS` times the retry count the SDK is
  configured for; waves are `ceil(size / VOTE_CONCURRENCY)`; the translator is
  one more request of the same family. Every term is already a sourced number
  in this repo, so the deadline is arithmetic over them rather than a guess.
- **Say the expectation before the wait, and name the failure after it.** The
  submit control says how many panelists are being asked; a run that passes the
  deadline ends as a stated error rather than an unbounded spinner.

## Deliberately NOT in this ticket

**`reasoning_effort` is never set in production.** It is fully plumbed —
`OpenRouterPanelLLM` takes it (`llm.py:220`), passes it (`llm.py:273`), and the
repo defines its own closed vocabulary for it (`llm.py:32`) — but the only
caller that supplies a value is a test (`test_llm.py:273`). `get_panel_llm`
(`main.py:54-59`) omits it, so all 25 votes run at gpt-5-mini's default effort,
spending reasoning tokens on "read a persona, pick one of two headlines, write
one line". Those tokens bill as output, so it costs latency and money at once.

It is not changed here because it is not a free win: effort is part of the vote
fingerprint (`llm.py:236-242`), so any change invalidates every cached vote, and
[015](015-task-framing-sensitivity.md) showed the verdict moves when the ask
moves. That makes it an experiment with a before/after against the numbers
above — its own ticket, not a line in this one.

## Related

- [021](021-progress-ux.md) — real progress streaming, still v2. This ticket is
  the honest floor beneath it: bounded, explained, and able to fail.
- `docs/research/first-full-scale-run.md` — every number used here.
