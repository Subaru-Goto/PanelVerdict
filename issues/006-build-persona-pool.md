---
title: "Build the persona pool (generate + persist with embeddings)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [001-decide-persona-schema-and-seed, 004-standup-skeleton-infra]
assignee: null
status: open
---

## Goal

Generate the v1 persona pool per the 001 schema:

- batched LLM generation with **anti-stereotype constraints**,
- **schema-validated typed fields** (no free text persisted),
- embeddings computed for fuzzy attributes,
- persisted to Postgres + pgvector.

Delivered as an idempotent seed script (safe to re-run).