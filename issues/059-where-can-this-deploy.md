---
title: "Where can this deploy? pgvector and a long-lived connection constrain the answer"
labels: [wayfinder:research]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Question

What is the deployment target for one FastAPI service, a Next.js frontend, and Postgres —
and what does it cost at demo scale?

Two hard constraints rule options out before preference does:

- **pgvector.** `schema.sql` uses a vector column with a `vector_cosine_ops` index, so the
  Postgres has to offer the extension — not every managed provider does, and some offer it
  only on paid tiers.
- **A long-lived connection.** [046](046-analyst-threads-die-on-restart.md) records that the
  checkpointer is process-lifetime and explicitly **cannot borrow `get_conn`**, which is
  per-request. A platform that freezes or recycles processes between requests breaks a
  durable checkpointer, so "serverless" is a correctness question here, not a cost one.

Also to establish:

- free-tier limits and cold-start behaviour — a cold start on the analyst is user-visible,
  and this is a demo people click once
- where secrets live on each platform, since the OpenRouter key is the asset the map's cost
  ceilings exist to protect
- whether the frontend and backend can share a provider, or whether Vercel + a separate
  backend host is the shape

Output: a markdown summary under `docs/research/` with a recommendation and the numbers.
**No invented prices** — quote the pricing page and date it, per the repo's rule against
unsourced constants.
