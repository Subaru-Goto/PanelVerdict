---
title: "Logs cannot be correlated to the request that produced them, and the id that would do it is minted too late"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The gap (sprint review feedback, 2026-08-03)

> *"Only three logger call sites in the entire application. No request-level tracing,
> no JSON structured logging, no correlation between an `/evaluate` request and its
> downstream model calls."*

Two things to correct before the real gaps, because both change what needs building:

- **There is already a correlation id on the line that matters most.**
  `pipeline.py:312` logs `test_id=%s` alongside wall time and the full usage totals.
  So a run's cost and duration *are* attributable today.
- **The logging pipeline was repaired recently, not neglected.** `main.py:37`
  records that every `logger.info` in this package was propagating to a handler-less
  root and being dropped at WARNING — *"a run's usage line … has never been readable
  from a running server, only from tests, which capture at the logger and so could
  not see the gap."* The lines existed; nothing emitted them.

## The three real gaps

**1. No timestamp.** `logging.basicConfig(format="%(levelname)s %(message)s")` — level
and message only. Every line is undated, which no aggregator can work with and which
makes the wall-time figure impossible to place in a sequence. This is smaller than
JSON output and matters more.

**2. `test_id` is inside the message, not beside it.** `"panel usage test_id=%s: …"`
is greppable but not queryable: no aggregator can filter on it without a regex, and
`total_usage(...)` is interpolated as a repr, so twelve numbers arrive as one opaque
string.

**3. Screening cannot be correlated at all.** `screening.py:194` and `:205` log a
refusal with no run identity, so *"which run was refused, and what did the customer
send"* is unanswerable from logs. That is the gap the feedback is really pointing at.

## The structural finding: the id exists too late, and means something else

Two reasons `test_id` cannot simply be threaded further back.

**It does not exist yet.** `/evaluate` runs `screen_inputs` *before* `run_panel_test`,
deliberately — *"before a single vote is bought, so a refused run costs nothing."*
But `test_id` is minted **inside** `run_panel_test` (`pipeline.py:261`). So at the
moment of the first loggable event there is no id to log, and a refused run never
gets one at all.

**And it is provenance, not a trace.** `pipeline.py:258`:

> *"A cached vote keeps the `test_id` of the run that paid for it — the ledger records
> provenance, and identity across runs is the fingerprint's job, not this id's."*

So a served row may carry a `test_id` from a *different* request. `test_id` answers
"which run paid for this vote"; a trace id answers "which request am I serving". They
diverge exactly when the cache hits, which is the case the ledger exists for.

**Therefore the correlation id is a new concept**, minted at the edge in `main.py`
for every request including refused ones, and carried *beside* `test_id` rather than
instead of it. Collapsing the two would quietly redefine what the ledger's id means.

## The trap: `contextvars` do not reach the vote workers

The obvious implementation is a `ContextVar` set by middleware and read by a
`logging.Filter`. It works for the endpoint and for screening, and it **silently
fails where the cost is**:

- `collect_panel_votes` fans out on a `ThreadPoolExecutor`
- `ThreadPoolExecutor.submit` does **not** copy the caller's context — each worker
  thread starts with an empty one, unlike an asyncio task, which does copy

So any log line emitted from a vote worker would carry a blank id, and the failure is
invisible: no exception, just an empty field on exactly the 25-at-a-time work anyone
would be tracing. Fixing it means wrapping the submitted callable
(`contextvars.copy_context().run(...)`) or passing the id explicitly as a parameter.
Worth stating because a naive implementation looks correct in tests, which are
single-threaded at the endpoint level.

## Dependencies: prefer the standard library

The feedback suggests `python-json-logger`. A JSON formatter is ~15 lines over
`logging.Formatter` with `record.__dict__`, and `logging.Filter` plus `ContextVar`
are both stdlib — so this is achievable with **no new dependency**, which the
minimal-dependency rule prefers. `structlog` is the option to reach for only if
key-value logging spreads beyond a handful of sites.

## Also worth doing in the same pass

`total_usage`'s twelve fields are the most valuable thing in the log and currently
arrive as a dataclass repr. Emitting them as **discrete fields** is what makes
"which runs cost more than $0.20" a query instead of a grep — and
[033](033-a-run-records-its-own-time.md) already established that the wall-time and
per-vote figures are the pair a slow run is diagnosed from.

## Done when

Every log line **is one JSON object per line** carrying a timestamp and a request id —
including a refused run, which has no `test_id` — the id survives into the vote workers
rather than blanking there, `test_id` still means what the ledger says it means, and a
run's usage totals are queryable fields rather than an interpolated repr.

JSON lines are named here deliberately, because the feedback asked for them
(*"switch to JSON-line output … so logs are machine-parseable in any aggregator"*) and
the dependency section above declines only the suggested **library**, not the format.
Declining `python-json-logger` while quietly dropping the requirement would be the
doc-claims-less-than-it-owes version of the failure this arc keeps finding.
