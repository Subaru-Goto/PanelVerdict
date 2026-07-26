---
title: "Pool-overview QC artifact: distributions vs. targets"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006f-persistence]
assignee: null
status: open
---

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
