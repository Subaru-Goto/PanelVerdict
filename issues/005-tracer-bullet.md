---
title: "Tracer bullet: 2 headlines → fixed panel → naive verdict, end to end"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [002-decide-vote-schema, 003-decide-panel-model-and-provider, 004-standup-skeleton-infra]
assignee: subaru
status: open
---

## Goal

Kill integration risk early with a thin end-to-end slice **using stubs**:

- 2 hardcoded headlines in,
- a tiny **fixed** panel (e.g. 5 hardcoded personas — no pool, no retrieval),
- real LLM votes using the 002 schema,
- a **naive count** verdict (no Bayesian yet),
- rendered in a minimal Next.js page via the API.

No targeting, no real pool, no posterior. Goal is proving the wires connect, not correctness of the verdict.