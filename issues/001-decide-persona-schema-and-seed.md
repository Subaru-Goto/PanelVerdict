---
title: "Decide persona schema + seed-data source + v1 pool size"
labels: [wayfinder:grilling]
parent: 000-map
blocked_by: []
assignee: subaru
status: closed
---

## Question

Three linked decisions:

1. **Schema** — what typed fields define a persona? Must support **hard** attributes (SQL-filterable) and **fuzzy** attributes (embeddable).
2. **Seed-data source** — real demographic/survey sources vs. a simpler synthetic seed adequate for v1?
3. **v1 pool size** — how many personas to pre-generate (~1–5k)?

Constraint: fields must be **schema-validated typed values, never free text** (pool-poisoning defense).

## Resolution (2026-07-16)

Grounded in deep research → [`docs/research/persona-attributes-grounding.md`](../docs/research/persona-attributes-grounding.md). Bottom line from that research: the evidence supports PanelVerdict's *architecture* (aggregate panel judgment, control group, population-level validation, competitor-relative cue modeling) more than *trait-targeting*, which stays a hypothesis the manipulation check must test. So v1 is deliberately minimal.

**Decisions:**

1. **Primitive = choose/prefer** (not click); vote is 3-way {A, B, neither} (see ticket 002). "Click" is the headline instantiation.
2. **Two-track schema:** filterable fields → SQL columns; behavior-shaping fields → rendered into the persona prompt (**Option B**: coherent persona → natural-language system prompt; *not* explicit susceptibility dials).
3. **v1 fields (minimal, grounded core):**
   - **Demographics** (age, gender, income, education, region) — SQL-filterable targeting handle. GROUNDED: US Census **ACS PUMS**.
   - **Interests** — relevance gate + fuzzy targeting (embedded). MUST-SYNTHESIZE (the one un-groundable field → stereotype hotspot, see checks).
   - **Big Five** (O/C/E/A/N) — behavior-shaper for within-segment diversity. GROUNDED (directional): **Donnellan & Lucas 2008** age-conditioned priors.
4. **Earn-their-place (NOT in v1):** Need for Cognition (verbal-complexity lever), Maximizing/Satisficing, CSII (social-proof lever). Each validated + ready, but added only when the **targeting manipulation check** shows it moves votes.
5. **Dropped:** mood/state (session-level, not a stored trait → per-run perturbation or drop) and past behavior (circular/self-referential for synthetic personas).
6. **Generation = C (hybrid):** sample groundable fields statistically — demographics from ACS PUMS (real joint distribution → congruent by construction), **Big Five continuous from the age-conditioned normal, then derive enum buckets from the realized sample** (realistic proportions by construction; v1 uses age-conditioned marginals — inter-trait correlations + gender effects are v2). LLM synthesizes only **interests + persona prose**, under anti-stereotype constraints.
7. **Pool size:** **5,000** personas for the v1 pool; **~200-persona dev subset** for fast iteration.
8. **Validate at the population/proportion level, never per-persona.** Congruence over quantity.

**On age (recorded to avoid over-weighting):** age→Big Five is real but *modest* (maturity principle: C peaks mid-life, A rises, O/E decline). Age's bigger role is as a demographic/targeting handle and proxy for media habits/interests. Age-conditioning Big Five is a cheap realism refinement, not load-bearing.

**Downstream:** generation pipeline + checks + pool-overview → acceptance criteria on **ticket 006**; injection screening of generated persona content shared with **ticket 013**.

**Addendum (2026-07-16):** Huang, Zhang, Soto & Evans 2026 (*Personality Science*, human-validated; Soto co-authored the BFI-2) refines *how* to render Big Five — psychometric **BFI-2-Expanded** sentences (never numeric), best on capable models — folded into tickets 006/008 (rendering) and 003 (Big-Five enactment fidelity is now a model-selection criterion, not just cost). Field set unchanged.
