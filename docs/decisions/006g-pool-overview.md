---
title: "Pool-overview QC artifact: distributions vs. targets"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006f-persistence]
assignee: null
status: done
---

## Resolution (2026-07-26)

`app/pool_overview.py` — `python -m app.pool_overview [--sample N]`. Run against a
freshly reseeded 200-persona dev pool: **worst of 64 comparisons was agreeableness
sd at z = +2.38**, which across that many z-scores is unremarkable. The sampler is
sound.

Two things the build turned on that are worth carrying forward:

- **The obvious Big Five check would have failed a correct sampler.** Personas are
  drawn from `MVN(μ(age, gender), Σ)` with Σ's diagonal at exactly 1.0, so
  "mean ≈ 0, sd ≈ 1" looks right — but μ moves with age and gender, and the law of
  total covariance gives `E[X] = E[μ]`, `Cov(X) = Σ + Cov(μ)`. The pool's expected
  openness mean is **−0.138**, not zero (the Donnellan & Lucas age gradient showing
  through a pool older than the norming reference). Realized: −0.137, z = 0.02. At
  the full 5,000 a naive check would have screamed at about nine standard errors on
  a perfectly healthy pool — and only at that size, so the bug would have surfaced
  exactly when it was most expensive.
- **Comparison is per country, not pooled.** Each joint table is its own claim; a
  US pool skewed one way against a JP pool skewed the other averages to a clean
  marginal neither table supports.

Marginals rather than cells, because a country table has 240 cells — even the full
pool leaves ~7 draws each, so a cell-level test reads noise.

## Goal

Emit a QC artifact over the persisted pool that validates it **at the population level** (never per-persona — 001):

- **Demographics** distributions vs. their seed targets (~~ACS~~ the OECD joint
  table, since 006b went multi-country).
- **Big Five** distributions vs. the 006a μ/Σ priors.
- ~~**Interest** frequency + diversity, with **stereotype-concentration flags**.~~
  *(removed 2026-07-26 — see below)*
- Browse individual personas.

Design basis: [001](001-decide-persona-schema-and-seed.md), [006](006-build-persona-pool.md).

## Amended 2026-07-26 — the interest panel goes, and the QC gets weaker

[006j](006j-persona-summary-embedding.md) removes generated interests, so there
is no interest frequency, diversity or stereotype concentration to display, and
[006e](006e-content-checks.md)'s dispersion metric that would have fed this panel
is retired with it.

**Worth being honest about what remains:** both surviving panels compare the pool
against the priors *our own samplers drew from* — demographics against the OECD
joint table, Big Five against the 006a μ/Σ. They catch a broken sampler, not an
unrealistic pool. [006i](006i-leisure-profiles.md) would have added the one
genuinely **external** check (realized participation vs published national
time-use figures) and was closed; its tables stay committed as reference data,
but with no leisure sampled into personas there is nothing realized to compare
them against. If external validation matters later, that is where to look first.

## Notes

- Overlaps `search_personas` ([012](012-build-analyst-chatbot-tools.md)): this audit is the **aggregate** view; the tool is drill-down.
