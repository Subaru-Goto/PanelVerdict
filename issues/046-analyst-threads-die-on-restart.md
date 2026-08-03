---
title: "Analyst threads are process-local, so a restart makes the analyst contradict itself"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The gap (sprint review feedback, 2026-08-03)

> *"`_CHECKPOINTER = InMemorySaver()` in `main.py` — a restart loses all conversation
> history, and a second worker would not share threads."*

**Half of this is already an accepted decision, and half is new.** `main.py:222`
records the acceptance:

> *"One saver for the process lifetime — threads must outlive requests, which is the
> whole point of a checkpointer. In-memory: a restart forgets every thread, accepted
> at v1 demo scale (the report the chat is scoped to lives client-side)."*

So *"a restart forgets threads"* was known and signed off, with a real mitigation: the
report itself travels in the `/chat` payload, so a restart never loses the thing the
customer paid for. **The second worker is the new part**, and it is the one that makes
this a deployment blocker rather than a scale-later nicety.

## The consequence nobody has written down

Neither the reviewer's note nor the code comment names the actual user-visible
failure, and it is worse than lost history.

`ChatRequest` records that *"the checkpointed transcript keeps ToolMessages, so a
follow-up is answered from context instead of re-buying the tool calls a text-only
replay would drop."* And the client mints one `thread_id` per rendered report, so it
keeps sending the same id after a restart.

Therefore, after a restart or on a second worker:

- the id resolves to an **empty** thread, not a missing one — nothing errors
- the follow-up **re-buys the tool calls** the transcript existed to avoid
- and the analyst answers with no memory of what it already said

The third is the real defect. A customer asks *"so which group was it again?"* and
gets an answer built from scratch, which may **disagree with the answer on screen
above it**. Silent inconsistency in the one component whose whole job is explaining
a number consistently. Losing history reads as a bug; contradicting yourself reads
as being wrong.

## The fix costs two dependencies, which needs sign-off

`PostgresSaver` is **not installed**, and neither is what it needs:

```
langgraph.checkpoint.postgres  MISSING
psycopg_pool                   MISSING
```

So this adds `langgraph-checkpoint-postgres` plus the `psycopg_pool` it pulls in,
against a standing rule that only packages the project directly needs get added.
The rule is satisfiable here — the project does directly need durable threads once
it is deployed — but it should be an explicit decision rather than a quiet install.

## Two structural mismatches to solve, not just a constructor swap

**1. Connection lifetime.** `get_conn` is documented as *"one plain connection per
request"* and closes with the request. The checkpointer is explicitly
process-lifetime. So it **cannot borrow `get_conn`** — it needs its own long-lived
connection or pool, created at startup and closed at shutdown. That is a new
lifecycle in an app that currently has none, and it is the substance of this ticket.

**2. Two schema owners.** `PostgresSaver.setup()` creates its own tables, while this
project has `apply_schema` and `db/` for DDL, and `get_conn`'s docstring is pointed
about the split: *"Deliberately NOT `prepare_connection`: that also runs schema DDL,
which is the seed's job, not a request's."* A saver that runs its own DDL at startup
contradicts that rule. Decide where `setup()` is called and write down why, or the
next reader will find two answers to "who creates tables".

## An open question this ticket should not settle by silence

**Should threads expire?** [040](040-vote-cache-read-window.md) gives votes a 24-hour
read window on the grounds that *"we do not need to reproduce old reports"*. A
durable thread is the same class of object: it is scoped to one rendered report, and
once that browser tab is gone the thread is unreachable — the `thread_id` lived only
in the client. So durable threads would accumulate rows nobody can ever read, which
is precisely the shape 040 deferred as *"a sweep"*.

Worth resolving in the same pass, because 040 already says how it ends: with auth
([045](045-paid-endpoints-have-no-auth-or-rate-limit.md)) a thread becomes **owned
content**, listed back to its user with CRUD, and retention stops being ours to
legislate.

## Done when

Two workers serve the same thread, a restart leaves a follow-up answering from the
transcript rather than from nothing, the checkpointer's connection has an explicit
lifecycle separate from `get_conn`, the DDL question has one written answer — and the
two new dependencies were signed off rather than discovered in the lockfile.
