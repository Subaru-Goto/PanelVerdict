---
title: "Seed-data research: Big Five age×gender norms (μ) + inter-trait correlation matrix (Σ)"
labels: [wayfinder:research]
parent: 006-build-persona-pool
blocked_by: []
assignee: null
status: open
---

## Question

The correlated-MVN Big Five sampler (006c) needs two grounding tables that do not exist yet. Source and cite them, from current large samples — don't trust memory:

1. **Age × gender Big Five domain norms** — mean vectors **μ** (O/C/E/A/N means per age band × gender). Candidate: Soto & John 2017 BFI-2 norms, or a recent large-sample equivalent.
2. **Domain inter-correlation matrix Σ** — the 5×5 empirical correlation matrix among domains. Candidate: a large recent open dataset (SAPA-project / IPIP) or a recent meta-analysis. May supersede the directional Donnellan & Lucas 2008 priors from 001.

Design basis: [001](001-decide-persona-schema-and-seed.md) (schema + sampling decisions, incl. the 2026-07-17 correlated-MVN amendment) and [006](006-build-persona-pool.md).

## Answer records

A cited note — `docs/research/persona-seed-data.md` — containing:

- **μ** in a form the 006c sampler can load directly (means per age band × gender, with SDs and the units/scale stated).
- **Σ** as a 5×5 correlation matrix (with the source sample described).
- Every figure attributed to a dated, primary source; note any conflicts and which we adopt and why.
- A short statement of how buckets are derived from the realized sample (continuous → `TraitLevel` LOW/MEDIUM/HIGH), so 006c has an unambiguous rule.
