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

## Decided (from ticket 001)

- **v1 fields:** demographics (age, gender, income, education, region) + interests + Big Five (O/C/E/A/N). NFC/maximizing/CSII are NOT in v1 (earned later via the manipulation check).
- **Generation = hybrid (C):**
  - Demographics — sample from **US Census ACS PUMS** (real joint distribution → congruent by construction). SQL-filterable.
  - Big Five — sample **continuous from the age-conditioned normal** (Donnellan & Lucas 2008 priors: shift the mean by age, apply population SD), then **derive enum buckets from the realized sample** so proportions are realistic by construction. v1 = age-conditioned marginals (inter-trait correlations + gender = v2). Behavior-shaper, prompt-rendered (not a targeting filter). **Render into the prompt as BFI-2-Expanded-style sentence descriptions of the sampled trait levels — never numeric/Likert** (best human-aligned enactment; Huang, Zhang, Soto & Evans 2026).
  - Interests — LLM-synthesized (the one un-groundable field), embedded for fuzzy targeting.
- **Sizes:** 5,000-persona v1 pool; ~200-persona dev subset for iteration.
- **Checks on LLM-written content (interests + prose), before persisting:**
  1. schema/type validation against a controlled vocabulary + length limits (reject/regenerate),
  2. injection screening (shared with ticket 013 — pool-poisoning defense),
  3. **anti-stereotype audit** — measure demographic→interest concentration; flag/regenerate over-concentrated slices (prompt-time anti-stereotype constraints help but the statistical audit is what catches it).
- **Pool overview (QC artifact):** emit distributions vs. targets (demographics vs. ACS; Big Five vs. priors), interest frequency + diversity with stereotype-concentration flags, and browse individual personas. Overlaps the `search_personas` tool (ticket 012) — audit = aggregate view, tool = drill-down.
- **Validate at the population level** (pool proportions match seed sources), never per-persona.