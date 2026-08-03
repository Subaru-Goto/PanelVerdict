---
title: "A vote that exhausts the SDK's retries is gone for the run — and there is no evidence that has ever happened"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The feedback, and the correction it needs

> *"`collect_panel_votes` … catches exceptions per-panelist and records them as
> `VoteFailure`, but never retries. **A single network hiccup permanently removes that
> panelist from the run.**"*

**The bolded claim is false, and the ticket exists partly to record why**, so nobody
adds a retry layer on top of the two that are already there.

Every call site sets `max_retries=2` — `llm.py:374, 420, 483, 520, 543` — stated
explicitly rather than inherited, and the comment says why:

> *"`max_retries` is the SDK's own default, stated rather than inherited: a panel fans
> 25 requests out at once, so 429s are expected traffic and this is the line that
> decides whether one costs a vote. The SDK backs off and honours `retry-after`."*

`collect_panel_votes`' own docstring already says *"A vote that fails **after the
client's own retries**"*. So a hiccup costs nothing; it takes **three consecutive
failures** to lose a panelist.

## The real gap, which is narrow

After the SDK's two retries are exhausted, that panelist is gone for the run. Nothing
at the chunk or run level tries again.

**And the reviewer's own supporting argument is the strongest case for fixing it:** the
fingerprint cache makes a re-attempt idempotent. Votes already cast are in the ledger
under their fingerprints, so a second pass cannot double-charge — it re-asks only the
panelists who have no row.

## What must never be retried

`402`. `llm.py:391`:

> *"The SDK retries 429/5xx itself; a 402 arrives here directly and is terminal for the
> whole run, not just this vote."*

The pipeline already breaks its chunk loop on `OutOfCredit` because *"every later chunk
would fail the same way, so fanning them out buys latency and nothing else."* A
re-attempt that caught every failure kind would undo that reasoning and spend minutes
re-asking questions guaranteed to be refused. Whatever ships must filter on failure
kind, the way `_failure_kind` already does.

## The measurement that decides whether this is worth building

**Zero vote failures have ever been observed.** `docs/research/first-full-scale-run.md`
records three runs: 200/200, 200/200, and 50/50 before an early stop — **0 failures in
450 paid votes.**

008 was explicit that the design does not rest on a rate: *"The failure rate is
unmeasured and this design does not rest on one."* It still doesn't. But 0-of-450 is
evidence, and it bounds the rate: the one-sided 95% upper bound is
`1 − 0.05^(1/450) ≈ 0.7%`.

At that upper bound, a 200-vote run loses **~1.3 panelists in expectation** — against a
panel whose own resolution is **±14 preference points** at that size
(`detectable_gap`). 199 votes and 200 votes do not produce different decisions.

**So the honest reading: this fixes nothing that has been observed to break, and at the
worst rate the evidence permits it would change no verdict.**

## And the case it *looks* like it covers is somebody else's

The scenario worth worrying about is not independent hiccups — it is a provider
degrading and failing *many* votes at once. That case is **already handled, and not by
a retry**:

- `PanelVotes` returns `records` and `failures` together, so a thinner panel is
  reported rather than hidden
- [010b](010b-partial-run-threshold.md) decides whether a partial run still deserves a
  verdict
- and a correlated outage is precisely when re-asking is *least* likely to succeed

So: independent failures are numerically negligible, correlated failures belong to
010b, and neither is a retry.

## If it is built anyway, build the cheap one

| option | cost | verdict |
|---|---|---|
| raise `max_retries` 2 → 3 | one character | **no** — the number would be a guess, and this repo does not ship unsourced constants; the SDK default is at least defensible as a stated default |
| chunk-level re-attempt inside the loop | moderate; interacts with adaptive stopping, since a chunk's tally would change after the stop check | no |
| **one run-level second pass** over the accumulated failures, filtered to non-402 kinds | small, and idempotent via the cache | **yes, if anything** |

The run-level pass is also the only one that cannot perturb
[010d](010d-adaptive-stopping.md): it happens after the loop, so no stopping decision is
made twice on different tallies.

## Done when

Either a failure is actually observed and a single non-402 run-level re-attempt lands
with a test proving the cache makes it free — or this ticket is **closed as wontfix**
with the 0-of-450 figure recorded, so the next reader does not re-derive it. Closing it
is the more likely outcome, and that is a finding rather than a failure.
