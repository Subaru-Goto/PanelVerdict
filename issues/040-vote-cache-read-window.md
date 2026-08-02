---
title: "The vote cache serves answers forever; it should only serve today's"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The requirement, decided 2026-08-02

> *"We do not need to reproduce old reports. Only when a user runs the same test in the
> same session it should show the same result. Another day, we do not need one."*

That is a **short-lived consistency guarantee**, not durable reproducibility — and it is
much cheaper to provide than what the ledger does today, which is serve any matching
answer forever.

## Two problems, and only one of them is this ticket

Tracing what clears the database ran these together for a while. They are independent and
need different mechanisms:

| want | mechanism | status |
|---|---|---|
| same test today → same result; tomorrow → fresh | a **read window** | this ticket |
| do not accumulate rows nobody can ever read | a **sweep** | deferred, see below |

## The fix needs no deletion

Today `load_votes` matches on the fingerprint alone, so a vote cast in July is still
served in August. One clause fixes it:

```sql
SELECT ... FROM votes
WHERE request_fingerprint = ANY(%s)
  AND created_at > now() - interval '24 hours'
```

Same test today → hit, identical result. Same test tomorrow → the row is still on disk but
is not *served*, so the run pays and draws a fresh panel. That is the requirement exactly.

Four things this keeps that a `DELETE` would cost:

- **Nothing paid-for is destroyed**, so the schema's append-only rationale stays true and
  needs no rewrite. A clearing policy would have made that comment false, which is the
  failure mode [038](038-education-reading-is-never-disclosed.md) hit three times.
- **Resume after a 402 still works** — topping up and re-running happens in minutes, far
  inside the window.
- **It is reversible.** Change the interval and behaviour changes; no data is gone while
  the number is still being judged.
- **No lifecycle hook, no session concept, no cron.**

## Prerequisite: the table has no timestamp

Columns today are `request_fingerprint, persona_id, test_id, chosen_variant_id,
presentation_order, reason`. So this needs `created_at timestamptz NOT NULL DEFAULT now()`
first. Additive, and `apply_schema` already has a path for columns added after the first
schema shipped.

## The number: 24 hours, signed off 2026-08-02

No derivation is available for this one, so it is a product choice rather than a measured
constant — legitimate under the repo's rule by explicit sign-off, and recorded here as
that rather than dressed up as arithmetic.

It is also the most defensible reading of the requirement, because it is the only part a
server can observe. *"Session"* cannot be implemented as stated: the backend never learns
that a browser closed. There is no auth, no cookie, no websocket — `/evaluate` and `/chat`
are stateless, and a closed tab is indistinguishable from a user who walked away. A
calendar day is what *"another day, we do not need one"* literally says, and it needs no
session abstraction the app has no other use for.

**Accepted cost:** rehearsing a demo the next day re-pays ~$0.15 and returns different
numbers. Within a day, replays stay free and byte-identical.

## Two options considered and rejected, so they are not revisited

**Clear on browser close.** Unobservable. `beforeunload` is skipped on crash, force-quit,
tab discard and mobile backgrounding, so it would work most of the time and silently fail
the rest — the worst property for something deleting paid data. It would also put a
destructive endpoint on an API with no auth.

**Clear on server startup.** Fails in both directions at once. Too rare to help: a server
up for weeks only clears on deploy, so accumulation is untouched. Too dangerous to be
safe: startup also means a crash restart, a recycled container, a rolling deploy, or a
second replica booting and wiping instance 1's cache **mid-run**, destroying votes already
paid for and breaking a resume in flight. It looks reasonable only because a developer
restarts constantly, which makes startup ≈ session — a property of how we work, not of the
system. Same class of mistake as reading the $10 key cap as a real bound.

## Why the sweep is deferred rather than bundled

Reclaiming storage is a separate decision with no urgency behind it. One test is at most
200 votes (`prod` size; `demo` 100, `dev` 25) at a few hundred bytes a row — roughly 80 KB
per test, so ~8 MB per hundred tests — and nothing is deployed yet (`docker-compose.yml`
carries only the `db` service). It needs the same `created_at` column this ticket adds, so
doing it later costs nothing extra.

**And it may never be the right shape**, see below.

## What supersedes this once there are users (v2)

Decided alongside the above: **once there is auth and a user base, an analysis becomes
owned content rather than an anonymous cache entry** — saved against the user, listed
back to them, with CRUD.

That changes the question rather than answering it. Today `votes` has no user column and
the API has no auth, so *any* policy is inherently cross-user: on a multi-user deployment
"clear for this visitor" would wipe another's paid votes. Age is the only dimension the
table currently has, which is why this ticket uses it.

With users, retention stops being ours to legislate — **keeping or deleting an analysis
becomes the user's choice**, which is what a delete on their own record means. So the sweep
this ticket defers might never be built as a sweep at all; it becomes the D in CRUD. Worth
recording so a future reader does not build a retention policy that a user-facing delete
then makes redundant.

## Done when

A test re-run inside the window returns the identical verdict for $0, the same test run
after the window pays and draws a fresh panel, and both are pinned by tests naming the
window rather than asserting a wall-clock date.
