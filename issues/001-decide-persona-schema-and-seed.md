---
title: "Decide persona schema + seed-data source + v1 pool size"
labels: [wayfinder:grilling]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Question

Three linked decisions:

1. **Schema** — what typed fields define a persona? (e.g. `age:int`, `gender`, `country`, `income_bracket`, `interests:list[str]`, `lifestyle`, …) Must support **hard** attributes (SQL-filterable) and **fuzzy** attributes (embeddable).
2. **Seed-data source** — where do the seed distributions come from: real demographic/survey sources (Census, Pew) vs. a simpler synthetic seed adequate for v1?
3. **v1 pool size** — how many personas to pre-generate (~1–5k)?

Constraint: fields must be **schema-validated typed values, never free text** (pool-poisoning defense — a malicious target description must not be able to inject instructions into a persisted persona).

**Answer records:** the field schema, the chosen seed source, and the v1 pool size.