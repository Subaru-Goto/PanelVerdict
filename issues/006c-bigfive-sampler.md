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

## In scope

- Sample continuous (O/C/E/A/N) from MVN(μ(age,gender), Σ).
- Apply the buckets-derivation rule from 006a → `BigFive` (`TraitLevel` LOW/MEDIUM/HIGH).
- Domain-level (5) only. Aspects (10) / facets (30) stay deferred (001) pending a post-quality-check revisit.

## Out of scope

- Prompt rendering already exists (`render_persona_prompt`, prose not numeric — 001/005). This ticket produces the sampled `BigFive`, not the rendering.
