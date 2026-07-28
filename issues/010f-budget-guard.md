---
title: "Budget guard: pre-flight check, graceful 402 stop, and a read timeout"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: [010a-vote-usage-instrumentation, 010e-per-vote-cache]
assignee: Subaru-Goto
status: closed
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

## Closed 2026-07-28

**The measured number decided, exactly as this ticket ordered.** The first full-scale run
([first-full-scale-run.md](../docs/research/first-full-scale-run.md), three runs, ~$0.17,
250 paid votes, 0 failures) put a 200-vote test at **~$0.145** ($0.000726/vote, superseding
010a's 10-vote figure upward by ~30%) — ~70 fixed-length tests inside the cap. That is the
"cheaper alternative" regime, so the elaborate pre-flight estimator was not built. What
shipped:

- **Pre-flight, decided as warn-and-proceed.** `GET /key` for `limit_remaining`
  (`llm.remaining_credit`, failure-tolerant: an unreadable meter returns None and None
  never warns), compared against `size × USD_PER_VOTE` (the measured constant, config.py).
  A thin balance is a `warning` notice with both figures and the remedy — never a refusal,
  because 010e makes a partial run worth having.
- **Graceful 402.** The adapter translates the SDK's generic `APIStatusError(402)` into
  `OutOfCredit` — the type *name* is the signal, since `VoteFailure` carries names only,
  and 402 is otherwise indistinguishable from any odd status (the 402-vs-429 decision: 429
  never reaches this path, the SDK retries it). The pipeline stops fanning out at the chunk
  boundary (later chunks would all fail; latency, not money), keeps the votes cast, and
  notices "top up and re-run to resume". Zero votes → HTTP **402**, not 502, with this
  codebase's own sentence.
- **Read timeout: 60s** (`VOTE_READ_TIMEOUT_SECONDS`) — ~3× the slowest of 250 timed votes
  (18.9s), ~4× the p99 (14.0s). A hang now costs a worker one minute, not the SDK's ten;
  no observed valid vote comes near it.

The paired run itself settled more than numbers: the cache replayed 200 votes for $0.00 in
19s (byte-identical verdict), the stop fired at the 50-vote floor on a decisive pair, and
the tied pair ran to cap with P(tie)=0.919 — equivalence is cap-priced in the flesh, as
simulated. Two behavioural findings recorded in the research doc: position bias saturates
to 100% on identical options, and the fixed per-chunk ORDER_SEED repeats its odd-chunk
surplus every chunk (a systematic ~2.6-vote lean per 200 at the 0.66 rate — a future
ticket's call, not this one's).

**Observed while testing, worth knowing:** two personas whose rendered prompts are
identical share one fingerprint, and therefore one cached vote — content is identity, by
010e's design. Real pool collisions are possible (trait *levels*, not scores, reach the
prompt); the effect is a slightly-less-independent panel, not a wrong vote. Recorded, not
acted on.

The 402 path is tested with doubles, not exercised live — credit never approached zero.

Accepted by design, on the record: the pre-flight notice prints the key's remaining
balance, and `/evaluate` has no auth — fine while this is a single-operator tool spending
its operator's own key, but if the API ever fronts untrusted multi-tenant traffic the
notice should drop the dollar figure (the security pass's one deliberate note).
