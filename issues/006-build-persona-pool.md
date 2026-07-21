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

## Children

This is an **umbrella** — the build is split into small, independently reviewable slices. Per-slice scope + open decisions live in each child ticket; the design basis for all of them is [001](001-decide-persona-schema-and-seed.md). 006 closes when every child closes.

- [ ] [006a](006a-seed-data-research.md) — seed-data research: μ (age×gender norms) + Σ (inter-trait correlation matrix)
- [ ] [006b](006b-demographics-sampler.md) — demographics sampler (ACS PUMS); settle age floor; type demographic fields
- [ ] [006c](006c-bigfive-sampler.md) — Big Five correlated-MVN sampler → enum buckets *(blocked by 006a)*
- [ ] [006d](006d-interests-synthesis.md) — interests synthesis + embeddings *(blocked by 006b, 006c)*
- [ ] [006e](006e-content-checks.md) — content checks: validation, injection screen, anti-stereotype audit *(blocked by 006d)*
- [ ] [006f](006f-persistence.md) — persistence: Postgres + pgvector + idempotent seed script *(blocked by 006b–006e)*
- [ ] [006g](006g-pool-overview.md) — pool-overview QC artifact *(blocked by 006f)*

## Decided (from ticket 001)

- **v1 fields:** demographics (age, gender, income, education, region) + interests + Big Five (O/C/E/A/N). NFC/maximizing/CSII are NOT in v1 (earned later via the manipulation check).
- **Generation = hybrid (C):**
  - Demographics — sample from **US Census ACS PUMS** (real joint distribution → congruent by construction). SQL-filterable.
  - Big Five — sample **continuous from a multivariate normal** (empirical inter-trait correlation matrix Σ), **mean-conditioned on age + gender**, then **derive enum buckets from the realized sample** so proportions are realistic by construction. **Amended 2026-07-17** (supersedes age-marginals-only; see 001 Amendment): correlations + gender promoted into v1; aspects/facets deferred to a post-quality-check revisit; domain-level (5) only. Behavior-shaper, prompt-rendered (not a targeting filter). **Render into the prompt as BFI-2-Expanded-style sentence descriptions of the sampled trait levels — never numeric/Likert** (best human-aligned enactment; Huang, Zhang, Soto & Evans 2026).
  - Interests — LLM-synthesized (the one un-groundable field), embedded for fuzzy targeting.
- **Sizes:** 5,000-persona v1 pool; ~200-persona dev subset for iteration.
- **Seed-data research (do first — the "small research for 006"):** source two grounding tables — (1) **age × gender Big Five domain norms** (mean vectors μ) and (2) the **domain inter-correlation matrix (Σ)** — from current large samples (candidates: Soto & John 2017 BFI-2 norms; SAPA-project / IPIP; recent meta-analyses). Produces a short cited note that feeds the sampler; may supersede the directional Donnellan & Lucas 2008 priors. Required by the correlated-MVN sampling promoted in the 001 Amendment (2026-07-17).
- **Checks on LLM-written content (interests + prose), before persisting:**
  1. schema/type validation against a controlled vocabulary + length limits (reject/regenerate),
  2. injection screening (shared with ticket 013 — pool-poisoning defense),
  3. **anti-stereotype audit** — measure demographic→interest concentration; flag/regenerate over-concentrated slices (prompt-time anti-stereotype constraints help but the statistical audit is what catches it).
- **Pool overview (QC artifact):** emit distributions vs. targets (demographics vs. ACS; Big Five vs. priors), interest frequency + diversity with stereotype-concentration flags, and browse individual personas. Overlaps the `search_personas` tool (ticket 012) — audit = aggregate view, tool = drill-down.
- **Validate at the population level** (pool proportions match seed sources), never per-persona.
