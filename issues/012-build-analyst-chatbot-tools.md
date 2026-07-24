---
title: "Build the 'Ask the analyst' chatbot + tools (chatbot requirement)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [010-assemble-orchestrator-graph, 011-build-report-ui]
assignee: null
status: open
---

## Goal

The chatbot + tool-calling requirement, embedded in the report and **scoped to the current test**:

- ≥3 tools (LLM decides *when*, deterministic code does *how*): `run_panel_test`, `search_personas`, `analyze_results` (+ optional `estimate_cost` / `get_test_history`),
- **suggested-question chips** rather than free composition (each chip maps to a requirement and demos reliably).

The exact chip set is fog until this ticket is worked (see map Notes).

## Notes

- **Vector index (deferred here from 006f).** `search_personas` needs the pgvector similarity index (HNSW/IVFFlat) on `interests.embedding` — 006f persists vectors but builds no index. Its migration must build the index with `CREATE INDEX CONCURRENTLY` (avoids locking the table), which **cannot run inside Alembic's default transaction** — wrap it in `op.get_context().autocommit_block()`. Also decide here whether search needs a per-persona mean-pooled embedding vs. querying per-interest rows.
