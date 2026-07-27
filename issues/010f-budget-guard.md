---
title: "Budget guard: pre-flight check, graceful 402 stop, and a read timeout"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: [010a-vote-usage-instrumentation, 010e-per-vote-cache]
assignee: null
status: open
---

## Goal

Make a run survive the **$10 hard cap**. Three pieces, together because all three need
numbers [010a](010a-vote-usage-instrumentation.md) measures and none is worth building on a
guess:

1. **Pre-flight check** — `GET /api/v1/key` for `limit_remaining`, estimate the run's cost,
   refuse or warn *before* spending anything.
2. **Graceful mid-run stop on 402** — mark the run partial, never emit a half-panel, and
   leave it resumable.
3. **A read timeout** on the vote call, replacing the SDK's 600s default.

All three are [003](003-decide-panel-model-and-provider.md)'s requirements, deferred here from
[008](008-build-panel-evaluation.md) because they are run-level rather than vote-level.

## Why each one needs 010a first

**The pre-flight estimate is the whole point of the check**, and there is currently no
per-test cost to estimate with: `$0.055` was retracted, not corrected. A check comparing
`limit_remaining` against a made-up number is a guess wearing a decimal point — worse than no
check, because it will refuse affordable runs or wave through unaffordable ones.

**The read timeout needs a measured latency distribution.** The SDK's default is 600s, so one
hung request holds a worker for ten minutes; with 25 workers, a few hangs stall a run. But a
timeout short enough to help would also cut off slow-yet-valid reasoning responses, turning a
vote into a failure — trading a stall for a thinned panel. The p99 of a real run is the only
defensible source for the number, which is why 010a records latency alongside tokens.

## The 402 stop, and why 008 has no circuit breaker

A rejected request **is not charged**. So a mid-run 402 costs latency, not money — which is
why 008 deliberately kept fanning out rather than tripping a breaker on the first failure, and
why this can be a considered policy rather than a panic.

What makes the stop *graceful* is [010e](010e-per-vote-cache.md): the votes already cast are
persisted, so topping up the credit resumes the run instead of repeating it. Without the
cache, "graceful stop" would just mean losing the run politely. That is the whole reason this
ticket is blocked on 010e rather than merely related to it.

Where the stop lands: [010d](010d-adaptive-stopping.md)'s chunk boundary is the only natural
checkpoint, since 008 fans out with a concurrency cap rather than discrete batches. If 010d
has not landed, a stop can only take effect after the whole panel has been attempted — which
is acceptable (nothing is charged) but should be stated rather than discovered.

## Decisions this ticket has to make

- **Refuse, or warn and proceed?** A run that will exhaust the credit part-way is not
  worthless once 010e can resume it — so "refuse" may be too strong, and "warn, run, resume
  later" may be the better product behaviour. This is a genuine choice, not an oversight.
- **Distinguish 402 from 429.** Both are HTTP failures arriving through the same path;
  429 is retried with backoff by the SDK and is expected traffic under a 25-way fan-out, while
  402 is terminal for the whole run. `VoteFailure.error` carries the exception type, which is
  where that distinction is currently visible.
- **What the endpoint says.** A refused-on-budget run is not a server error. `/evaluate`
  currently 502s when any vote fails; a budget refusal wants its own status and a message a
  human can act on ("top up and resume"), without leaking key or account details — the
  existing 502 deliberately reports exception *types* only, and that discipline should hold.

## A cheaper alternative to consider first

If a real 200-vote run turns out to cost only a couple of cents, the $10 cap is ~hundreds of
runs and an elaborate pre-flight check is over-engineering. In that case the honest v1 is: log
the cost per run, cap the panel size, and rely on 010e to resume the rare 402.

**So run 010a before designing this**, and let the measured number decide how much machinery
this ticket deserves. That ordering is the point of splitting them.
