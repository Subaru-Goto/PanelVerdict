---
title: "Build the persona pool (generate + persist with embeddings)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [001-decide-persona-schema-and-seed, 004-standup-skeleton-infra]
assignee: null
status: open
---

## Goal

Generate the v1 persona pool per the 001 schema:

- ~~batched LLM generation with **anti-stereotype constraints**~~ — **amended 2026-07-26:** no LLM generation remains in the pool build (see [006j](006j-persona-summary-embedding.md)); every field is sampled or templated, and the only model call is the summary embedding,
- **schema-validated typed fields** (no free text persisted),
- embeddings computed for fuzzy attributes,
- persisted to Postgres + pgvector.

Delivered as an idempotent seed script (safe to re-run).

## Children

This is an **umbrella** — the build is split into small, independently reviewable slices. Per-slice scope + open decisions live in each child ticket; the design basis for all of them is [001](001-decide-persona-schema-and-seed.md). 006 closes when every child closes.

- [x] [006a](006a-seed-data-research.md) — seed-data research: μ (age×gender norms) + Σ (inter-trait correlation matrix) — *done, PR #9*
- [x] [006b](006b-demographics-sampler.md) — demographics sampler (per-country US/JP/DE); country/culture_tag; type demographic fields; settle age floor — *done, PR #14*
- [x] [006c](006c-bigfive-sampler.md) — Big Five correlated-MVN sampler → enum buckets — *done, PR #17*
- [~] [006d](006d-interests-synthesis.md) — interests synthesis + embeddings — *shipped PR #19, now **superseded** by [006j](006j-persona-summary-embedding.md); removed in its slices 2-3*
- [~] [006e](006e-content-checks.md) — content checks: injection denylist, anti-stereotype audit, plausibility G-Eval — *shipped PRs #21/#22/#23, now **partly superseded** by [006j](006j-persona-summary-embedding.md): the audit is retired, the denylist moves to [013](013-guardrails-mvp.md)*
- [x] [006f](006f-persistence.md) — persistence: Postgres + pgvector + idempotent seed script + QC report — *done, PRs #25/#26/#27/#28; example-bank follow-up PR #29*
- [ ] [006g](006g-pool-overview.md) — pool-overview QC artifact *(blocked by 006f — now unblocked)*
- [~] [006h](006h-menu-mode-interests.md) — menu-mode interests — *rejected: required ~430 invented weights; superseded by 006i*
- [~] [006i](006i-leisure-profiles.md) — leisure profiles from surveyed time-use — *data layer merged (PRs #31/#33/#34/#36/#37) and kept as reference data; leisure does not enter the persona. Closed 2026-07-26: no evidence it moves a vote, and it made each new country a bespoke extraction*
- [ ] [006j](006j-persona-summary-embedding.md) — persona summary embedding; `interests` dropped *(replaces generated interests; blocks the production seed and 007's vector half)*

## Decided (from ticket 001)

- **v1 fields:** demographics (age, gender, income, education, region) + ~~interests~~ + Big Five (O/C/E/A/N). **Amended 2026-07-26 ([006j](006j-persona-summary-embedding.md)):** interests dropped; a templated persona summary + its embedding replaces them. NFC/maximizing/CSII are NOT in v1 (earned later via the manipulation check).
- **Generation = hybrid (C):**
  - Demographics — sample from **US Census ACS PUMS** (real joint distribution → congruent by construction). SQL-filterable.
  - Big Five — sample **continuous from a multivariate normal** (empirical inter-trait correlation matrix Σ), **mean-conditioned on age + gender**, then **derive enum buckets from the realized sample** so proportions are realistic by construction. **Amended 2026-07-17** (supersedes age-marginals-only; see 001 Amendment): correlations + gender promoted into v1; aspects/facets deferred to a post-quality-check revisit; domain-level (5) only. Behavior-shaper, prompt-rendered (not a targeting filter). **Render into the prompt as BFI-2-Expanded-style sentence descriptions of the sampled trait levels — never numeric/Likert** (best human-aligned enactment; Huang, Zhang, Soto & Evans 2026).
  - Interests — LLM-synthesized (the one un-groundable field), embedded for fuzzy targeting. **Reversed 2026-07-26 ([006j](006j-persona-summary-embedding.md)):** un-groundable turned out to mean unusable — four designs failed to control the distribution, and the two that could ground it (menu-mode, leisure profiles) cost invented weights or a bespoke extraction per country. The persona carries no interests; fuzzy targeting embeds a templated summary of demographics + Big Five instead.
- **Sizes:** 5,000-persona v1 pool; ~200-persona dev subset for iteration.
- **Seed-data research (do first — the "small research for 006"):** source two grounding tables — (1) **age × gender Big Five domain norms** (mean vectors μ) and (2) the **domain inter-correlation matrix (Σ)** — from current large samples (candidates: Soto & John 2017 BFI-2 norms; SAPA-project / IPIP; recent meta-analyses). Produces a short cited note that feeds the sampler; may supersede the directional Donnellan & Lucas 2008 priors. Required by the correlated-MVN sampling promoted in the 001 Amendment (2026-07-17).
- ~~**Checks on LLM-written content (interests + prose), before persisting:**~~ **Amended 2026-07-26 ([006j](006j-persona-summary-embedding.md)):** all three are moot once no LLM writes a persona field — validation has nothing to validate, the pool-poisoning path closes by construction (013 keeps the screening for *user* input), and demographic→interest concentration cannot exist without interests. What replaces the audit is checking the sampled distributions against the priors they were drawn from (006g).
- **Pool overview (QC artifact):** emit distributions vs. targets (demographics vs. the OECD joint table; Big Five vs. priors), ~~interest frequency + diversity with stereotype-concentration flags~~ (removed 2026-07-26), and browse individual personas. Overlaps the `search_personas` tool (ticket 012) — audit = aggregate view, tool = drill-down.
- **Validate at the population level** (pool proportions match seed sources), never per-persona.
