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

## Amended 2026-07-27 (010) — the tool loop is LangChain in v1

[010](010-assemble-orchestrator-graph.md) dropped LangGraph from v1, so this ticket does
not get to reach for it either: v1 builds the tool loop on LangChain's tool calling with the
message list held by the request.

This is also the ticket where the decision gets revisited. A multi-turn chat with a tool
loop, message history across turns, and possibly confirmation interrupts is the *idiomatic*
LangGraph case — unlike the linear panel pipeline, where it was not. So if v2 adopts it,
adopt it here, and let this ticket's own experience of hand-rolling the loop be the
evidence for whether it is worth the dependency. Note what the graded requirement actually
names: **tool calling**, which is this ticket's content and is framework-independent.

## Notes

- **Vector index (deferred here from 006f).** `search_personas` needs the pgvector similarity index (HNSW/IVFFlat) on ~~`interests.embedding`~~ **`personas.summary_embedding`** — 006f persists vectors but builds no index. **Amended 2026-07-26 ([006j](006j-persona-summary-embedding.md)):** the index target moves to one vector per persona, and the open question of "per-persona mean-pooled embedding vs. querying per-interest rows" is moot — the `interests` table is dropped, so there is exactly one vector to search.

  **This note assumed Alembic, which does not exist.** 006f never introduced migrations, and 006j D6 decided against them on purpose: the sampled columns are a pure function of `master_seed`, so the pool is a cache and drop-and-reseed replaces a migration. So the index is a plain `CREATE INDEX` in `schema.sql`, run by `apply_schema` like the rest.

  The concurrency advice survives the change and still has to be honored *if* migrations ever arrive — which is the moment the pool stops being reproducible, i.e. when votes and test results are persisted alongside it. It said: build with `CREATE INDEX CONCURRENTLY` (avoids locking the table), which **cannot run inside Alembic's default transaction**, so wrap it in `op.get_context().autocommit_block()`. Note `CONCURRENTLY` is pointless on a freshly seeded pool with no readers, so this only matters for an index added to a live pool.
- **pgvector adapter on pooled connections.** If the search runtime uses a `psycopg_pool.ConnectionPool`, register the vector adapter per connection via the pool's `configure=` callback — use **`register_vector`** alone, NOT 006f's `prepare_connection` (which also runs `apply_schema` DDL and must not fire on every checkout).
