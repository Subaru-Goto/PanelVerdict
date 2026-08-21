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

Grounded in deep research → [`docs/research/persona-attributes-grounding.md`](../research/persona-attributes-grounding.md). Bottom line from that research: the evidence supports PanelVerdict's *architecture* (aggregate panel judgment, control group, population-level validation, competitor-relative cue modeling) more than *trait-targeting*, which stays a hypothesis the manipulation check must test. So v1 is deliberately minimal.

**Decisions:**

1. **Primitive = choose/prefer** (not click); vote is 3-way {A, B, neither} (see ticket 002). "Click" is the headline instantiation.
2. **Two-track schema:** filterable fields → SQL columns; behavior-shaping fields → rendered into the persona prompt (**Option B**: coherent persona → natural-language system prompt; *not* explicit susceptibility dials).
3. **v1 fields (minimal, grounded core):**
   - **Demographics** (age, gender, income, education, region) — SQL-filterable targeting handle. GROUNDED: US Census **ACS PUMS**.
   - **Interests** — relevance gate + fuzzy targeting (embedded). MUST-SYNTHESIZE (the one un-groundable field → stereotype hotspot, see checks).
   - **Big Five** (O/C/E/A/N) — behavior-shaper for within-segment diversity. GROUNDED (directional): **Donnellan & Lucas 2008** age-conditioned priors.
4. **Earn-their-place (NOT in v1):** Need for Cognition (verbal-complexity lever), Maximizing/Satisficing, CSII (social-proof lever). Each validated + ready, but added only when the **targeting manipulation check** shows it moves votes.
5. **Dropped:** mood/state (session-level, not a stored trait → per-run perturbation or drop) and past behavior (circular/self-referential for synthetic personas).
6. **Generation = C (hybrid):** sample groundable fields statistically — demographics from ACS PUMS (real joint distribution → congruent by construction), **Big Five continuous from the age-conditioned normal, then derive enum buckets from the realized sample** (realistic proportions by construction; *superseded by Amendment 2026-07-17 — v1 now uses correlated MVN sampling conditioned on age + gender*). LLM synthesizes only **interests + persona prose**, under anti-stereotype constraints.
7. **Pool size:** **5,000** personas for the v1 pool; **~200-persona dev subset** for fast iteration.
8. **Validate at the population/proportion level, never per-persona.** Congruence over quantity.

**On age (recorded to avoid over-weighting):** age→Big Five is real but *modest* (maturity principle: C peaks mid-life, A rises, O/E decline). Age's bigger role is as a demographic/targeting handle and proxy for media habits/interests. Age-conditioning Big Five is a cheap realism refinement, not load-bearing.

**Downstream:** generation pipeline + checks + pool-overview → acceptance criteria on **ticket 006**; injection screening of generated persona content shared with **ticket 013**.

**Addendum (2026-07-16):** Huang, Zhang, Soto & Evans 2026 (*Personality Science*, human-validated; Soto co-authored the BFI-2) refines *how* to render Big Five — psychometric **BFI-2-Expanded** sentences (never numeric), best on capable models — folded into tickets 006/008 (rendering) and 003 (Big-Five enactment fidelity is now a model-selection criterion, not just cost). Field set unchanged.

**Amendment (2026-07-17) — Big Five sampling fidelity (supersedes "correlations + gender = v2" in decision 6):**

After a psychometric deep-dive, two items deferred to v2 above are **promoted into v1**:

- **Gender added to mean-conditioning** (age → **age + gender**). Gender is a robust, moderate effect (women ~+0.4–0.5 SD Neuroticism, ~+0.3–0.4 SD Agreeableness; Costa, Terracciano & McCrae 2001) — cheap to add, meaningfully more realistic.
- **Correlated sampling** — draw the five domains from a **multivariate normal with the empirical inter-trait correlation matrix (Σ)**, not five independent normals. Captures the meta-trait structure (Stability, Plasticity; DeYoung 2006, Digman 1997) and — the load-bearing reason for us — **reduces incongruous trait stacks that degrade LLM steerability (~9.7%)**. So it is an *enactability* upgrade, not just realism. Enum buckets still derived from the realized sample (unchanged).

**Stays deferred:** aspects (10) / facets (30) — **domain-level (5) for v1; revisit after inspecting result quality** (DeYoung, Quilty & Peterson 2007; NEO-PI-R, Costa & McCrae 1992).

**Deliberately excluded (rationale recorded — not oversights):**
- **Culture/nation means** — the reference-group effect makes national mean comparisons unreliable (McCrae & Terracciano 2005; Heine et al. 2002), even though the factor structure replicates across cultures (Gurven et al. 2013 Tsimane = partial exception). Conditioning on it would inject noise as signal.
- **SES/education** — small and confounded.
- **Measurement artifacts** (IRT precision-at-extremes, Likert ceiling/floor) — these are *instrument* properties, not latent-trait properties. We sample the latent trait and render it as prose (not a simulated questionnaire), so we deliberately **do not** reproduce them. Skew (A/C negative, N positive; Roberts, Walton & Viechtbauer 2006; Soto et al. 2011) approximated as Gaussian for v1.
- Greater male variance on some traits — real but tiny; deferred.

**Seed data required (two tables; sourcing = a small research pass under [006](006-build-persona-pool.md)):**
1. **Age × gender Big Five domain norms** (mean vectors μ) — candidate: Soto & John 2017 BFI-2 norms / a recent large sample.
2. **Domain inter-correlation matrix (Σ)** — candidate: a large recent open dataset (SAPA-project / IPIP) or recent meta-analysis. May supersede the directional Donnellan & Lucas 2008 priors.

Field set unchanged (demographics + interests + Big Five).

## Amendment (2026-07-21) — multi-region grounding, Big Five μ conditioning, and language

Resolved via a design grill (feeds 006a–006f). Supersedes decision 3's implicit single-population (US ACS PUMS) assumption.

**v1 is multi-region — seed three countries: Japan, US, Germany.** A synthetic-panel tool whose pool is one country can't honestly serve a marketer targeting another region. "Western" spans {US, DE}, so the coarse-targeting mechanism is genuinely exercised (a tag mapping to >1 country). All three have both Big Five grounding (DE = the GSOEP half of Donnellan & Lucas 2008; US = Soto 2011 / Kajonius & Johnson 2019 corroboration; JP = BFI-2-J) and a national census (ACS / Destatis-Eurostat / e-Stat).

**Grounding key = country, not continent.** Demographics must be sampled from a real national census ("congruent by construction"); there is no "Asian" or "Western" census. So each persona is grounded in exactly one **country/locale**. Continent/culture ("Asian", "Western") is a **derived `culture_tag`** over the country key, used only for coarse *targeting* — the targeting vocabulary stays coarse while the grounding key stays country-precise. A coarse request ("Asian audience") resolves to the seeded countries carrying that tag; **coverage = the seed list** (unseeded regions/countries return empty — a 007 concern).

- **Schema implication (006b):** add a top-level **country/locale** field (grounding key); **`culture_tag` (Western/Asian) is derived** from it, not stored. `income`/`education` (currently free `str`) get typed in 006b (income → within-country quintile; education → ISCED). **Sub-national region is dropped for v1** (2026-07-21) under "earn their place" — small vote effect, not conditioned into Big Five, most expensive field to type; the region concept that matters (Western/Asian) is `culture_tag`. Add sub-national region back only if targeting shows it moves results.
- **Pool sizing:** each country is an independent 001-style pool (5,000 full / ~200 dev subset). Develop + demo at **~200/country**; full per-country size is a tunable one-shot batch (006f). Adding personas or **new countries later is a data/config operation** (census + culture_tag), not a rewrite — the pipeline is country-parameterized.

**Big Five μ conditioning — decision (i): country does NOT condition μ.** Every country uses the **same shared age/gender z-scored contrasts** (Donnellan & Lucas 2008; see 006a research note). Considered and rejected:
- **(iii) per-country *absolute* means** ("Japanese lower on Extraversion than Americans") — the **reference-group-effect artifact** this ticket already excluded (Heine et al. 2002; McCrae & Terracciano 2005; Terracciano et al. 2005). Ruled out.
- **(ii) per-country contrasts, each z-scored *within its own country*** — dodges the artifact (no cross-national level comparison) and would *use* the Japan sources, but rejected for v1: Japan's per-country norm data is weak (BFI-2-J = 2 age bands, N=500), the age/gender structure is ~universal (maturity principle replicates cross-culturally; Bleidorn et al. 2013), and it would turn every future country into a per-country norm research project (undercutting cheap expansion).

Culture's *behavioral* effect on votes enters through **demographics + interests + the LLM enacting a culturally-situated persona**, not a Big Five mean shift. The Japan sources (BFI-2-J etc.) are retained as **validation checks** that the structure + age direction hold there (they do — older Japanese show lower N, higher C/A/O, matching D&L).

**Language is not an engineered generation channel.** The test's language is carried by the marketer's **headline input**; the panel model (gpt-5-mini) is natively multilingual and evaluates it as-is — nothing to build. Persona prompts stay **English** for v1; language-matched persona rendering (+ reasoning) is a deferred **fidelity refinement** tied to the reason-quality eval (006). Language selection lives at the **frontend/presentation layer** — the marketer views the report and chats with the analyst in a chosen language (i18n at 011/012).
