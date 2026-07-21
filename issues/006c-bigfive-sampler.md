---
title: "Big Five sampler: correlated MVN conditioned on age+gender → enum buckets"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006a-seed-data-research]
assignee: null
status: open
---

## Goal

Draw the five domains from a **multivariate normal** using the empirical inter-trait correlation matrix **Σ**, with means **mean-conditioned on age + gender** (μ from 006a), then **derive `TraitLevel` enum buckets from the realized sample** — so pool proportions are realistic by construction.

Design basis: [001](001-decide-persona-schema-and-seed.md) (2026-07-17 amendment: correlated sampling + gender promoted into v1; the load-bearing reason is reduced incongruous trait stacks that degrade LLM steerability, ~9.7%) and [006a](006a-seed-data-research.md) for μ/Σ.

## Decided approach (2026-07-21 grill)

- **Store the continuous sampled score as the source of truth** — not the bucket. `TraitLevel` is **derived at render** via a pure `bucketize(score)`. Payoff: render granularity (3→5 levels) becomes a one-function change, no re-sampling; and the 006g QC can validate sampled means/correlations against μ/Σ (buckets alone are a weaker check). **Supersedes the tracer-era `BigFive` (`TraitLevel`-only) — this ticket changes the schema to carry floats.**
- **Fixed cutoffs, not pool tertiles.** Tertiles need the whole-pool distribution (breaks the pure-function property) *and* re-centre each targeted subgroup on itself, erasing the age/gender conditioning. Fixed cutoffs on the z-scale (from 006a) preserve the conditioned lean.
- **Why this is correct (validated against "target 45+"):** conditioning μ on age+gender shifts a subgroup's distribution; fixed cutoffs read that shift off faithfully → a realistic mix (leans high/low per the trait's age trend, but keeps the tail) — neither deterministic "all HIGH" stereotyping nor tertile-forced ⅓. Direction falls out per-trait from μ (C/A rise with age → lean high; O/N decline → lean low). Age effect is *modest* (001), so leans are gentle.
- **Age→μ uses discrete bands** (006a-reported); age itself is stored as the real value. Changing bands later costs a re-sample (the μ choice is baked into the stochastic draw) — accepted, since bands rarely change.

## In scope

- Sample continuous (O/C/E/A/N) from MVN(μ(age,gender), Σ).
- Apply the buckets-derivation rule from 006a → `BigFive` (`TraitLevel` LOW/MEDIUM/HIGH).
- Domain-level (5) only. Aspects (10) / facets (30) stay deferred (001) pending a post-quality-check revisit.

## Out of scope

- Prompt rendering already exists (`render_persona_prompt`, prose not numeric — 001/005). This ticket produces the sampled `BigFive`, not the rendering.
