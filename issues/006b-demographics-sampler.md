---
title: "Demographics sampler: joint sampling from ACS PUMS + settle age floor + type demographic fields"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: []
assignee: null
status: open
---

## Goal

Sample the demographic fields (age, gender, income, education, region) from **US Census ACS PUMS**, drawing from the **real joint distribution** so slices are congruent by construction (not five independent marginals). SQL-filterable.

Design basis: [001](001-decide-persona-schema-and-seed.md), [006](006-build-persona-pool.md).

## In scope

- Load/prepare an ACS PUMS extract and sample joint demographic rows.
- **Harden the demographic fields into typed values** in `backend/app/schemas.py` — income / education / region are currently free `str` (a tracer-era placeholder). Replace with controlled vocab / enums so "no free text persisted" holds (001).

## Open decision — age floor (decide here, with the data in front of you)

The tracer (005) defaults `Persona.age` to `ge=18` as a conservative placeholder, not a decision. Settle it — a three-way trade-off:

- **Market coverage** — teens (13–17) are a real marketing audience; an 18+ pool can't serve advertisers targeting them, though ACS PUMS has the data.
- **Psychometric grounding** — the Big Five norms (006a, age-conditioned) are validated on adults; conditioning minors' traits extrapolates past the seed data.
- **Ethics/compliance** — simulating minors for marketing testing touches COPPA (<13) and ad-to-minors standards; 18+ sidesteps it.

Whatever is chosen, update the `Persona.age` constraint in `backend/app/schemas.py` to match.
