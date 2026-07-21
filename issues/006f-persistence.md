---
title: "Persistence: Postgres + pgvector schema + idempotent seed script"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006b-demographics-sampler, 006c-bigfive-sampler, 006d-interests-synthesis, 006e-content-checks]
assignee: null
status: open
---

## Goal

Assemble the sampled demographics (006b) + Big Five (006c) + validated interests/embeddings (006d/006e) into full personas and **persist to Postgres + pgvector**, delivered as an **idempotent seed script (safe to re-run)**.

Design basis: [001](001-decide-persona-schema-and-seed.md), [006](006-build-persona-pool.md).

## In scope

- Postgres schema: hard fields as SQL columns (filterable); embeddings in pgvector.
- Idempotent seed: re-running does not duplicate or corrupt the pool.
- **Sizes:** 5,000-persona v1 pool; ~200-persona dev subset for fast iteration.
