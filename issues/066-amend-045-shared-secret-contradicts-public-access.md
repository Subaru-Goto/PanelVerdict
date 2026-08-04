---
title: "Amend 045 — its shared secret contradicts a public deployment"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Goal

[045](045-paid-endpoints-have-no-auth-or-rate-limit.md) proposes *"a shared-secret header and
a per-key rate limit before anything is deployed."* That was correct for a **private**
deployment and is incompatible with this map's destination: **you cannot both let strangers
in and gate on a shared secret.**

Amend it rather than close it — the ticket's analysis survives, only its mechanism changes.

What to record:

- the shared secret is replaced by **verified identity** ([063](063-google-login-verified-at-the-edge.md))
  for spending, and by **nothing at all** for reading the demo
  ([061](061-a-zero-cost-demo-page.md))
- its per-key rate limit becomes the layered scheme in
  [064](064-the-cost-ceilings.md), where the **global daily cap** is the load-bearing layer
  rather than any per-caller limit
- **what it already got right, and should be preserved rather than re-derived:** that
  LangChain middleware cannot serve an HTTP limit, because it runs inside the agent after the
  stream has begun and can never return a 429. That finding generalises to auth and is now
  one of this map's standing decisions — *the edge refuses, the middleware bounds.*

**On ownership, since the frontmatter and the body could look contradictory:** this ticket is
a child of [the public-demo map](055-map-public-demo.md) — writing the amendment is *this*
map's work. The ticket being amended, [045](045-paid-endpoints-have-no-auth-or-rate-limit.md),
stays a child of [000-map](000-map.md) and is not re-parented. Doing the work here, leaving
the artifact there.
