---
title: "Demographics sampler: joint demographics per country (US/JP/DE) + typed fields + age floor"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: []
assignee: null
status: open
---

## Goal

Sample the demographic fields (age, gender, income, education, sub-national region) for the three seeded countries — **US, Japan, Germany** (001 amendment 2026-07-21) — each from its own national statistics source, drawing from the **real joint distribution** so slices are congruent by construction (not independent marginals). Add the **country/locale** grounding key + derived **culture_tag**. SQL-filterable.

Design basis: [001](001-decide-persona-schema-and-seed.md) (esp. the 2026-07-21 multi-region amendment), [006](006-build-persona-pool.md).

## The central challenge

"Sample from a census" is trivial for the US (ACS PUMS = public individual-level microdata → joint is free). The hard part is getting **comparable joint** demographics from three different national statistics systems, which may publish very different things (Germany/Japan may only expose aggregate cross-tabs, or gate microdata behind research-data-centre applications).

## Sequence (research-first — decided 2026-07-21)

1. **Data-source research pass** → `docs/research/demographic-sources.md`: what's publicly available per country (microdata vs cross-tabs), native category schemes, access/licensing, IPUMS-International coverage of DE/JP, harmonization options. *(in progress)*
2. **Harmonization + fidelity decisions** (grill — see open decisions).
3. **Schema evolution** (`backend/app/schemas.py`): add `country` + `culture_tag`; type `region` (sub-national, country-dependent vocab), `income`, `education` per the harmonization decision; set the age floor. Kept atomic — done after 1–2 so fields aren't typed twice. (`BigFive` → continuous is **006c**, not here.)
4. **The sampler**: per-country joint draw (direct microdata, or IPF-reconstructed from cross-tabs), fixed seed, dev at ~200/country.

## Open decisions

- **Fidelity strategy (when true microdata isn't public):** (A) microdata everywhere (may need restricted-access applications); (B) hybrid — US from PUMS, JP/DE reconstruct the joint from public cross-tabs via **iterative proportional fitting (IPF)**; (C) best-available, falling back to independent marginals where joint isn't public (retreat from 001's congruence). *Decide after the research pass.*
- **Harmonization of income/education:** per-country typed vocabularies (faithful, not cross-comparable) vs an international standard (**ISCED** for education; PPP or within-country quantiles for income). Determines how the schema types these fields.
- **Age floor** — the tracer's `ge=18` is a placeholder. Three-way trade-off, now cross-country:
  - *Market coverage* — teens (13–17) are a real audience; 18+ can't serve them.
  - *Psychometric grounding* — the 006a Big Five norms are validated on adults (D&L covers down to 16); conditioning minors extrapolates.
  - *Ethics/compliance* — simulating minors touches COPPA (<13, US) and equivalents in JP/DE; 18+ sidesteps it.
  - Whatever is chosen, update `Persona.age` in `backend/app/schemas.py`.

## Resolved (2026-07-21, post data-source research + user-supplied JP sources)

See [`docs/research/demographic-sources.md`](../docs/research/demographic-sources.md).

- **Fidelity = (B) hybrid** — the data forces it (microdata-everywhere is infeasible): **US** direct from ACS PUMS; **DE** demographics direct from **Destatis public cross-tabs** (no institutional affiliation → not IPUMS-International) + income IPF from Mikrozensus bracket cross-tabs; **JP** IPF from public e-Stat cross-tabs.
- **Harmonization:** education → **ISCED 2011** (~5 coarse levels); income → **within-country quantiles** (not PPP — congruent-by-construction, and consistent with the no-cross-country-comparison stance).
- **Japan income upgraded (🔴→🟡):** individual, same-frame **就業構造基本調査 (Employment Status Survey 2022)** — collects individual 所得 + 世帯所得 jointly with age×sex×education×prefecture; corroborated by **賃金構造基本統計調査** (employees-only). Removes the household→individual bridge; Japan now ~on par with Germany.
- **Age floor = 18** (2026-07-21). Cleanest ethics/compliance posture across US/JP/DE and future-proof against the regulatory trend restricting under-18s online (e.g. Australia's under-16 social-media ban and similar pushes). Grounded (inside the D&L 16–19 band) and simplest — matches the tracer's existing `Persona.age = Field(ge=18)`, so no schema change for the floor. Documented limitation: no teen (13–17) coverage — an acceptable, increasingly regulation-aligned v1 boundary.
