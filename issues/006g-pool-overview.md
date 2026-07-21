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

- **Demographics** distributions vs. ACS targets.
- **Big Five** distributions vs. the 006a μ/Σ priors.
- **Interest** frequency + diversity, with **stereotype-concentration flags**.
- Browse individual personas.

Design basis: [001](001-decide-persona-schema-and-seed.md), [006](006-build-persona-pool.md).

## Notes

- Overlaps `search_personas` ([012](012-build-analyst-chatbot-tools.md)): this audit is the **aggregate** view; the tool is drill-down.
