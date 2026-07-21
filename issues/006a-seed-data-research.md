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

## Decided inputs (2026-07-21 grill)

- **Units: z-scores** (mean 0, SD 1 per trait). Scale-free, so the bucket cutoffs (006c) are portable and "a score of X" is unambiguous. If a source reports on a raw scale (e.g. BFI-2 1–5), convert to z using that source's mean/SD and record the conversion.
- **Age bands: the research picks the partition** the best source actually reports (do not impose 18–29/30–44/… a priori). Report the bands the norm data uses, and we adopt them.
- **Bucketing is render-derived, not stored** — so this note must specify a *fixed-cutoff* rule on the z-scale (e.g. `z<−0.5 → LOW`, `z>0.5 → HIGH`; confirm exact cutoffs against the norm distribution). Fixed (not pool-tertile) so age/gender conditioning survives into targeted subgroups. Rationale + validation live in 006c.

## Answer records

A cited note — `docs/research/persona-seed-data.md` — containing:

- **μ** in a form the 006c sampler can load directly (means per age band × gender, with SDs and the units/scale stated).
- **Σ** as a 5×5 correlation matrix (with the source sample described).
- Every figure attributed to a dated, primary source; note any conflicts and which we adopt and why.
- A short statement of how buckets are derived from the realized sample (continuous → `TraitLevel` LOW/MEDIUM/HIGH), so 006c has an unambiguous rule.
