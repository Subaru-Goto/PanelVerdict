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

## What shipped, and what is still parked

**Shipped: proof the run is alive.** A pulsing dot and a ticking elapsed
counter under the form — "Each panelist is reading both headlines and picking
one — 4s so far." A disabled button looks identical whether the panel is voting
or the request died, which is exactly how a slow run gets read as a broken one;
a number that keeps moving settles it, and it costs the backend nothing.

Deliberately **not** a progress bar. Nothing on the client knows how far along
a run is, and a bar that guesses would be a worse lie than no bar at all. Real
progress needs streaming, which is [021](021-progress-ux.md).

**Parked: the deadline and the estimate.** Both were built and reverted. They
depend on the client learning the panel size from `/health`, and they were
started *before* anyone knew why a run was slow — dressing a symptom whose
cause was still unknown. [033](033-a-run-records-its-own-time.md) then measured
it: a cold run of 25 fresh votes takes **11.6s**, inside the documented p99. So
the unbounded-request defect is real but not urgent, and the estimate would
have been describing a wait that turns out to be brief.

The one line worth keeping from that work: `fetch` still has no `AbortSignal`,
so a genuinely dead run hangs forever. Unpark when that bites for real.

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
