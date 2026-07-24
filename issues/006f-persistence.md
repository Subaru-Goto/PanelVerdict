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

## Resolved (2026-07-24 grill) — design

- **D1 — Scope: assemble → persist (idempotent) → QC report; regen deferred.** 006f samples/synthesizes/embeds → assembles full personas → persists idempotently → prints an audit (006e) + plausibility (006e) QC summary. The flag→**regenerate** loop (006e's `avoid`-hint machinery) is a *separate later slice*, not 006f. Persist-then-report, don't orchestrate correction.
- **D2 — Schema: two tables, per-interest child rows.**
  - `personas`: `id` (PK) + hard demographic columns (country, age, gender, income_quintile, education) + **five Big Five score columns** (`double precision`, storing 006c's continuous scores — levels derived at render, not stored). `culture_tag` is **not** stored (derived from `country`).
  - `interests`: one row per (persona, interest) — `persona_id` FK (`ON DELETE CASCADE`) + `interest text` + `embedding vector(1536)`, keyed `PRIMARY KEY (persona_id, interest)`. Per-interest embeddings (006d D4) can't be an array column — pgvector holds one vector per row; this table *is* the junction 012's similarity search scans. **No `position` column** (interests are an unordered set; the text key also dedups per persona). **No persona-level embedding and no vector index in 006f** — mean-pool + ivfflat/hnsw are search-perf concerns, deferred to 012.
  - **Enums stored as `text`, not native Postgres `ENUM`.** Python (pydantic) is the source of truth and validates at load; a native enum duplicates that in the DB catalog and — with no migration tooling yet — evolving it (`ALTER TYPE ... ADD VALUE`, non-transactional, no removal/reorder) is painful. Promote only once the value set stops churning; prefer a `CHECK (col IN (...))` constraint (light `ALTER TABLE` swap) over a native enum (wants migrations first).
  - **Star-schema / interest-dimension rejected at this grain.** A dimension table (`interests_dim` + FK/array reference) pays off only when the factored-out thing is *low-cardinality and heavily reused* (classic `product_dim`). 006d's **open vocab** makes raw interests high-cardinality and near-unique per persona → dedup ratio ≈ 1:1, so a dim table saves ~nothing while adding join cost; and Postgres `int[]` can't carry real FKs (no integrity/cascade). The dimension pattern **does** fit the low-cardinality **categories** discovered by 006g's topic model — defer it there.
- **D3 — Idempotency: ordinal id + fixed seed + skip-existing.**
  - `id = "{country}-{ordinal}"` (e.g. `US-00042`) — a **per-country counter**, not a content hash (interests are LLM-nondeterministic, so a content hash would treat every re-run as new personas → duplicates). The id is a stable *label*; you **never regex/parse it** — filter on the `country` **column**. **No pool-version token in v1** (YAGNI): the MVP has one pool, so multi-pool coexistence + a `pool_version` column earns its keep only if two pools must live in the same tables at once — add it back then, not now.
  - Idempotency rests on a **fixed RNG seed** so slot *i* is reproducible, applied via **per-slot seeding** (derive each slot's RNG from `(seed, country, i)`, not one shared stream) so the pool is **extendable** — appending slots leaves existing personas byte-identical. Within-country distribution stays correct automatically (each persona is an independent draw from the same ACS-grounded distribution); the only hand-managed knob is the **cross-country quota**.
  - **Skip-existing**, not upsert: `INSERT … ON CONFLICT (id) DO NOTHING` → idempotent + **resumable** (a crashed 5k-call run continues where it stopped) + preserves the first pool (no wasted LLM/embedding re-spend). One **transaction per persona** (persona row + its interest rows) so a crash can't leave a persona with no interests.
  - **Start a fresh pool** = `TRUNCATE personas CASCADE` + re-seed (cheap — regenerable pool, local Docker; the `interests` FK cascade clears child rows). This is an explicit non-seed action; re-running the seed itself only ever inserts.
  - **Naming:** the product/release axis (**v1** = MVP: text-only, 3 countries, small pool, local Docker; **v2** = images/other inputs, more countries, deployed) is a **roadmap concept, not part of the id or schema** — it describes app capabilities + where it runs, not persona identity.
- **D4 — Schema management: raw idempotent DDL for v1; migrations deferred to v2.** v1 is local Docker with a **regenerable** pool, so there is no production data to protect and the v1 schema history is throwaway — migration tooling buys nothing yet. v1 ships a `schema.sql` (`CREATE EXTENSION / TABLE IF NOT EXISTS`) applied by the seed script's init step; the schema is free to churn (`drop + re-seed` costs minutes). **v2 (deploy to Supabase)** adopts a migration tool — Alembic (raw-SQL migrations, `target_metadata=None`, `alembic`/`sqlalchemy` in a dev-only dependency group so app runtime stays psycopg, DSN wired to `settings.database_url`) **or** Supabase's own SQL migrations; the **first migration = the final v1 schema as a baseline**, tracked from there because production data now exists.
  - **pgvector caveats (attach to v2's migration work):** (a) `CREATE INDEX CONCURRENTLY` can't run inside a migration's default transaction — but 006f builds **no vector index** (deferred to 012), so this only bites 012's index migration, which must use an autocommit block; (b) run migrations against Supabase's **direct/session connection (port 5432)**, never the **transaction pooler (6543/PgBouncer)**, which breaks DDL/prepared statements.
- **D5 — Orchestration: dev-first validation → threaded full run.**
  - Per-persona pipeline (order fixed by data deps): sample demographics+BigFive (seeded) → synthesize interests (LLM) → screen (`content_checks`) → embed (batched) → assemble `Persona` → persist (1 txn, `ON CONFLICT DO NOTHING`). After all personas: run the 006e audit + plausibility eval on a sample and **print a QC summary** (no regen — D1).
  - Concurrency: **bounded `ThreadPoolExecutor` (~8–16 workers)** for interest synthesis (the sync LangChain layer needs no async rewrite). **Embeddings computed inline per persona** — each `assemble_persona` embeds its own interests, so `AssembledPersona` is a complete unit and one worker = one persona end-to-end. *Cross-persona request-batching was considered and dropped:* embeddings are the cheap leg (per-**token** billing, ~$0.002 total; threading already covers wall-clock), and batching adds a silent scatter/gather misalignment risk for a ~5% gain. Revisit only if the embedding endpoint RPM-throttles (a contained refactor of this seam). **Validate correctness on the dev subset / a handful first, then enable threading for the full run.**
  - CLI: `python -m app.seed --size dev|full --seed N [--countries US,JP,DE]`. Commit **one transaction per persona** as you go (resumability). Cost brake: dev-first + a one-line "about to make N calls" print before a full run (no interactive gate — premature at MVP).
- **D6 — Testing: stub what we control, real DB for what we can't fake.**
  - **Unit** (no network/DB; stub the `InterestLLM`/`Embedder`/`Judge` Protocols): id derivation (`US-00042` format + per-slot seed **reproducibility** and **independence** — the dev-subset-is-a-prefix property), persona assembly + one-vector-per-interest alignment, QC-report assembly from stubbed audit/eval outputs.
  - **Integration** (real Postgres + pgvector via **`testcontainers`**): **idempotency** (double-seed → row count unchanged, i.e. `ON CONFLICT DO NOTHING` skips), **pgvector round-trip** (dims/values preserved — proves the `pgvector.psycopg` adapter is wired), **`schema.sql` idempotent apply** (run twice, no error), **transaction-per-persona atomicity + cascade**. Mocking these would test the mock, not `ON CONFLICT`/pgvector reality.
  - Adds **`testcontainers`** as a dev/test dependency (directly needed). Pure-logic slices TDD-first; integration tests written alongside the DB code.
