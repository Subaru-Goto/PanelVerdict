# Persona Attributes — Evidence Grounding (research for ticket 001)

*Date: 2026-07-16 · Method: `deep-research` workflow, two passes (5 search angles each; ~50 verified claims across runs). Feeds ticket 001 "Decide persona schema + seed-data source."*

> **Status: input, not gospel.** Both passes complete (pass 2 backfilled the groundability + LLM-enactability angles that failed in pass 1). Findings are verified adversarially (vote shown) or flagged as unverified/refuted.

## Key terms (plain-language)

- **Big Five (a.k.a. OCEAN / Five-Factor Model):** the most scientifically validated model of human personality. Five broad traits, each a spectrum: **O**penness (curious, imaginative, novelty-seeking ↔ conventional, practical), **C**onscientiousness (organized, disciplined, reliable ↔ spontaneous, careless), **E**xtraversion (outgoing, energetic ↔ reserved, solitary), **A**greeableness (warm, cooperative, trusting ↔ critical, competitive), **N**euroticism (anxious, emotionally reactive ↔ calm, resilient). We give each persona five scores, sampled from real population data.
- **BFI-2 (Big Five Inventory-2):** a widely-used, validated questionnaire (Soto & John 2017) for measuring the Big Five. Two *prompting formats* matter here: **BFI-2-Expanded** = describe a persona's trait levels in full sentences (best at making an LLM actually enact the personality); **BFI-2-Likert** = numeric agreement ratings (worst). We render Big Five as Expanded sentences.
- **Need for Cognition (NFC):** how much a person enjoys effortful thinking — high-NFC prefer detailed, information-dense content; low-NFC prefer simple. *(Deferred past v1.)*
- **Maximizing vs. Satisficing:** a decision style — *maximizers* exhaustively compare to find the best option; *satisficers* take the first "good enough." *(Deferred past v1.)*
- **CSII (Consumer Susceptibility to Interpersonal Influence):** a validated scale for how much a person is swayed by others' opinions / social proof. *(Deferred past v1.)*
- **Sensation-seeking:** craving novel, intense stimulation; drives preference for *visually* complex designs (relevant to the image/design era, not v1 headlines).
- **ACS PUMS (American Community Survey — Public Use Microdata Sample):** free US Census *individual-level* records; we sample from these so the persona pool has realistic demographic proportions.
- **Manipulation check / control group:** validation methods — assign a group a known preference and check the panel's verdict shifts *relative to a control group* in the predicted direction. It's how we test whether persona targeting actually works.

---

## TL;DR — what this changes

1. **Keep the field set small AND mutually congruent.** LLM personas use only a limited, biased subset of provided fields; and steerability *drops ~9.7% for incongruous multi-trait personas*, which then fall back to demographic stereotypes. Many stacked dials → incoherent agents. *(verified 3-0)*
2. **Validate at the population/proportion level, never per-persona.** LLM personas are group-good, individual-poor (individual accuracy <5%; group agreement up to 0.86). PanelVerdict aggregates hundreds into a vote split — the regime where these models work. *(verified 3-0)*
3. **The trait → headline-choice link is UNVALIDATED, and there's a deeper enactability gap.** No verified study shows a persona trait predicting Upworthy headline clicks. Worse: LLMs shift *self-reported* traits far more than *behavior* (dissociation), so even in principle a persona may "say" it's cautious without *choosing* cautiously. The **manipulation check** and Upworthy targeting-effect test exist to catch exactly this. *(verified 3-0)*
4. **Creative-cue effects are the strongest on-task evidence and directly actionable** — including the architectural constraint: **score a variant relative to its competitor, not as an absolute.**
5. **Groundability is confirmed** for the core fields with concrete public sources (see the seed table).
6. **Both design tensions resolved** as provisionally decided: drop mood/state as a stored trait (per-run perturbation); do not seed past behavior.
7. **How you *render* a trait matters as much as which trait you pick.** Psychometric **BFI-2-Expanded** prompting (each trait level described in full sentences) gives human-aligned Big Five enactment (r≈0.90) on capable models, while numeric/Likert rendering is *worst* — so the "traits don't move behavior" pessimism is partly a **prompting-format artifact**. Render Big Five as expanded sentences, never numbers; verify fidelity on the cheap panel model (fidelity is model-dependent). *(Huang, Zhang, Soto & Evans 2026 — human-validated; treat as our most on-point source.)*

---

## Verified findings

### Creative-cue effects (strongest on-task evidence — all on the Upworthy corpus)

- **Emotional valence.** Each additional **negative** word raised CTR ~2.3%/word (β≈0.015, P<0.001); each **positive** word *lowered* it ~1.0%/word. *(3-0.* Robertson et al. 2023, *Nature Human Behaviour* — s41562-023-01538-4.)
- **Concreteness is inverted-U AND relative to the choice set.** More concrete helps only when rivals are vague, hurts when rivals are already concrete (interaction −0.058, P<0.001). **→ Architectural constraint: score a variant relative to what it competes against.** *(3-0.* Le Quéré & Matias 2024/25, *Scientific Reports* — s41598-024-81575-9.)
- **Curiosity gap = Loewenstein's information-gap mechanism** (confirmed), but curiosity/clickbait features *alone don't cleanly predict clicks* — model as one *non-monotonic* cue, not a driver. *(3-0 theory; ML-quantifiability medium.* Golman & Loewenstein.)

### Persona traits with validated instruments

- **Need for Cognition (NFC) — CORRECTED.** NFC drives preference for **verbal/textual** complexity (relevant to headlines); preference for **visual** complexity is driven by **sensation-seeking**, not NFC. The original "NFC → visual polish" attribution was **refuted (0-3)**. NFC scale is contested as multidimensional (Lord & Putrevu 2006: 4 factors). *Sources: Martin, Sherrard & Wentzel 2005, Psychology & Marketing (mar.20050); NFC scales (sjdm.org).* **Take:** keep NFC as the *verbal-complexity* lever for headlines; hold sensation-seeking for the design/image era.
- **Maximizing vs. Satisficing.** Validated: Schwartz 13-item scale (α~.71) + Nenkov 6-item short form; three factors (Alternative Search, Decision Difficulty, High Standards). Maximizers search/compare more. *(3-0.* Schwartz 2002 *JPSP*; Nenkov 2008.) **Caveat:** modest reliability; validated on product purchases, not headline clicks.
- **Consumer Susceptibility to Interpersonal Influence (CSII).** Validated two-dimensional scale (normative + informational) — the proper instrument for the social-proof cluster (subsumes candidate fields 11/12/13). *(3-0.* Bearden, Netemeyer & Teel 1989, *JCR*.) **Caveat:** general consumer influence, not headline-specific.

### Groundability — seed sources (confirmed in pass 2)

- **Demographics** (age, gender, income, education, region) → **US Census ACS PUMS** — free individual-level microdata for custom joint distributions (data.census.gov, Census Microdata API). *(3-0.)* **GROUNDED.**
- **Big Five** → **Donnellan & Lucas 2008** (*Psychology and Aging*, PMC2562318): age-conditioned priors from BHPS (N≈14k) + GSOEP (N≈21k) — Extraversion & Openness decline with age, Agreeableness rises, Conscientiousness peaks ~40–49. *(3-0.)* **GROUNDED (directional; cross-sectional; Neuroticism inconsistent).**
- **Values / cultural orientation** → **Joint EVS/WVS 2017–2022 v5.0.0** (GESIS ZA7505): 92 countries, 156k+ respondents. *(3-0.)* **GROUNDED.**
- **Maximizing, CSII** → validated scales exist (above); no census-style norms → **distribution MUST-SYNTHESIZE from the scale.**

### Structural cautions (the load-bearing risks)

- **Trait variance is mostly within-person** (62–78%). Stable trait scores predict a single momentary choice weakly — but trait *means* predict *aggregate* tendencies, and PanelVerdict aggregates. *(3-0.* Fleeson & Gallagher 2009, *JPSP*, PMC2791901.)
- **LLM enactability is asymmetric and fragile.** Models shift **self-reported** traits under persona prompts, but this frequently **fails to move behavior** (Han et al. 2025 "Personality Illusion": persona injection shifted self-reported agreeableness β=3.95 p<.001 but not sycophancy behavior β=0.03 p=.67). Steerability drops ~9.7% for **incongruous** personas → default to demographic stereotypes (Liu, Diab & Fried 2024). LLMs misportray/flatten identity groups (Wang et al. 2025, *Nat. Mach. Intell.*). Demographic conditioning *differentiates* output but does **not** reliably *match* real human distributions (Argyle "algorithmic fidelity"/"effective proxy" claims **refuted**). *(mostly 3-0.)* Sources: arXiv 2307.00184, 2509.03730, 2405.20253; nature.com/s42256-025-00986-z; Argyle 2023 *Political Analysis*.
- **Counter-nuance — psychometric prompting rescues Big Five enactment (our most on-point source).** With **BFI-2-Expanded** prompts (each trait level described in full sentences), agent responses align with human data: risk-taking prediction r≈0.89–0.91 on newer LLMs (vs. 0.80 human baseline), and Big-Five↔moral-dilemma correlations mirror humans. **BFI-2-Likert (numeric) was the *worst* format; simple adjectives in between.** Fidelity is **model-dependent**: GPT-4/4o/DeepSeek-V3/Llama-3.3-70B ≫ GPT-3.5. Limitation: still can't fully substitute for humans in high-precision work; safety-alignment skews moral judgments. *(human-validated, n=438+276; Huang, Zhang, Soto & Evans 2026, Personality Science — Soto co-authored the BFI-2.)* → **Design rules:** render Big Five as expanded sentences (never numeric); verify enactment on the *cheap* panel model. This meaningfully softens the dissociation pessimism above — with the right format and model, Big Five enactment is real.

---

## Design tensions — resolved

- **Field 19 (context/state: device, time pressure, mood).** Do **not** store as a stable trait. Model as a **per-run stochastic perturbation** (log the draw for reproducibility) **or drop for v1**. *(grounded in Fleeson & Gallagher.)*
- **Field 20 (habitual/past behavior).** Do **not** seed it in v1 — synthetic personas have no real history; fabricating it is circular, accumulating their own votes is self-referential. *(grounded in the enactability findings.)*

*(Neither tension was closed by a returned claim; both are argued from the structural findings + first principles.)*

---

## Provisional v1 field set (for ticket 001 to finalize)

Small, congruent, validated-where-possible, validated at population level:

| Field | Role | Grounding / seed source |
|---|---|---|
| Demographics (age, gender, income, education, region) | targeting handle + baseline; also anchors Big Five priors | **GROUNDED** — ACS PUMS |
| Interests / topical domains | relevance gate + fuzzy targeting (embedded) | MUST-SYNTHESIZE |
| Big Five (O/C/E/A/N) | aggregate diversity | **GROUNDED (directional)** — Donnellan & Lucas 2008, age-conditioned; **render via BFI-2-Expanded sentences, never numeric** (Huang et al. 2026) |
| Need for Cognition (verbal-complexity lever) | detail-dense vs. simple headline preference | validated scale; distribution MUST-SYNTHESIZE |
| Maximizing / Satisficing | choice-overload / "good enough" | validated scale; MUST-SYNTHESIZE |
| CSII (interpersonal influence) | the social-proof lever (subsumes 11/12/13) | validated scale; MUST-SYNTHESIZE |

Rules that fall out of the evidence:
- **Congruence over quantity** — generate coherent, non-contradictory personas (fits the Option-B holistic generation decision); incongruous stacks degrade steerability.
- Creative-cue effects (negativity, relative concreteness, curiosity-as-non-monotonic) are **modeled in the panel/analysis, not persona fields**, scored relative to the competing variant.
- Sensation-seeking is the *visual*-complexity lever → **defer to the design/image era**, not v1 headlines.

**Deferred to v2 (unvalidated, not disproven):** regulatory focus, risk tolerance, price sensitivity, tech adoption, locus of control, time preference, numeracy, trust disposition. (Cultural orientation / self-construal are folded into CSII + the EVS/WVS grounding.)

---

## Do not use — refuted claims

- "NFC predicts **visual**-complexity preference." **Refuted 0-3** (it's sensation-seeking; NFC = verbal).
- "97%-accuracy curiosity clickbait classifier ⇒ strong click signal." **Refuted 0-3** (detection ≠ prediction).
- GPT "algorithmic fidelity" — demographic backstories reproduce real subgroup distributions. **Refuted 1-2.**
- "LLMs are effective proxies for specific human subpopulations." **Refuted 0-3.** (Surviving nuance: they *differentiate* by demographic; they don't *match* real distributions.)
- "Rich personas → near-zero individual accuracy → trait personas useless." **Refuted 0-3** (surviving nuance: group-good/individual-poor).

---

## Upworthy usage caveats (for effort A)

- **Filter ~7,004 tests (22%, Jun 25 2013 – Jan 10 2014)** — Author Correction flags randomization problems.
- Data is **aggregate per-arm CTR for headline+image packages**, not per-person A/B/neither — bounds "individual-level" validation and makes headline-only framing a slight overreach.
- Archive: Matias et al. 2021, *Scientific Data* (s41597-021-00934-7) — 32,487 experiments, 150,817 arms, 538M+ assignments.

---

## Open questions

1. Does any persona field predict two-headline **click**-choice specifically (vs. Upworthy), or only generic product/website preference? **Central unvalidated assumption of a trait-driven panel.**
2. Given the self-report/behavior dissociation, do persona prompts shift LLM *creative/preference choices* (the actual output modality), not just questionnaires?
3. At what panel size do aggregate proportions become reliable vs. Upworthy per-arm CTR?
4. Correct baseline "neither"/non-click rate for headline feeds, given Upworthy is forced package-selection (no true opt-out)?

---

## Summary & Conclusion

**Summary.** The evidence base splits cleanly in three. (1) *Creative-cue effects* on headline clicks are real, measured on the exact Upworthy ground truth, and directly usable — negativity raises CTR, positivity lowers it, and concreteness has an inverted-U effect that is **relative to the competing headline**. (2) *Persona traits* have validated, publicly groundable instruments — demographics (ACS PUMS), age-conditioned Big Five (Donnellan & Lucas), values/culture (EVS/WVS), maximizing (Schwartz/Nenkov), CSII (Bearden) — but essentially all of their relevance evidence comes from product/website decisions, **not** two-headline click choice. (3) *LLM enactment* of traits is fragile: models shift self-reported traits far more than behavior, lose steerability on incongruous multi-trait personas, flatten identity groups, and the optimistic "LLMs faithfully emulate subpopulations" claims were refuted. Personas are **group-good, individual-poor**.

**Conclusion.** This research validates PanelVerdict's *architecture* more than its *trait-targeting premise*. The parts that stand on solid ground are: aggregate panel judgment (not per-persona accuracy), a control group to isolate targeting effects, population-level validation against Upworthy, and modeling creative cues relative to the competitor. The part that remains an unproven **hypothesis** is that persona traits steer *creative choices* toward what real humans do — no source establishes it, and the enactment literature is actively skeptical. That hypothesis is exactly what the **targeting manipulation check** and the **Upworthy targeting-effect test** are designed to falsify cheaply, before any weight is placed on it.

The design implications are therefore conservative and concrete:

1. **Small, mutually-congruent, fully-groundable core.** Prefer demographics + interests + Big Five (all groundable) over a wide psychographic stack; congruence beats quantity.
2. **Earn psychographic richness.** NFC (verbal-complexity lever), maximizing, and CSII are validated and ready, but each should be added only when the manipulation check shows it moves votes — not on faith.
3. **Validate at the population level**, never per-persona; report panel vote-split vs. Upworthy CTR-split.
4. **Model creative cues in the pipeline, relative to the competing variant** — this is where the strongest evidence actually lives.
5. **Treat trait-targeting as a tested hypothesis, not a feature**, until the manipulation check passes.
6. **Rendering format is first-class.** Express Big Five as psychometric **BFI-2-Expanded** sentences (not numbers, not one-word levels); enactment fidelity is *model-dependent*, so verify it on the cheap panel model — a model-selection criterion, not just cost. *(Huang et al. 2026 — our most on-point, human-validated source; it partly rehabilitates trait enactment given the right format + model.)*

Net: the honest headline is *"the machinery is well-supported; whether persona traits add predictive signal over demographics-plus-cues is an open question we've built the tests to answer."*

---

## Sources (verified, primary unless noted)

**Creative cues / Upworthy:** Robertson et al. 2023 *Nat. Hum. Behav.* (s41562-023-01538-4); Le Quéré & Matias 2024/25 *Sci. Reports* (s41598-024-81575-9); Golman & Loewenstein (cmu.edu); Matias et al. 2021 *Sci. Data* (s41597-021-00934-7).
**Traits / scales:** Martin, Sherrard & Wentzel 2005 *Psych. & Marketing* (mar.20050); NFC scales (sjdm.org); Schwartz et al. 2002 *JPSP* (bschwartz.domains.swarthmore.edu/maximizing.pdf); Nenkov et al. 2008 (cambridge.org); Bearden, Netemeyer & Teel 1989 *JCR* (academic.oup.com/jcr/article-abstract/15/4/473/1816002).
**Groundability:** ACS PUMS (census.gov/programs-surveys/acs/microdata/access.html); Donnellan & Lucas 2008 *Psych. & Aging* (PMC2562318); Joint EVS/WVS 2017–2022 (gesis.org).
**Structural / LLM enactability:** Fleeson & Gallagher 2009 *JPSP* (PMC2791901); "Pay What LLM Wants" 2025 (arxiv 2508.03262); Serapio-García et al. 2023 (arxiv 2307.00184); Han et al. 2025 "Personality Illusion" (arxiv 2509.03730); Liu, Diab & Fried 2024 (arxiv 2405.20253); Wang, Morgenstern & Dickerson 2025 *Nat. Mach. Intell.* (s42256-025-00986-z); Argyle et al. 2023 *Political Analysis*; **Huang, M., Zhang, X., Soto, C., & Evans, J. (2026). "Designing AI-Agents With Personalities: A Psychometric Approach." *Personality Science.* https://journals.sagepub.com/doi/10.1177/27000710251406471 (DOI 10.1177/27000710251406471) — BFI-2-Expanded prompting; most on-point / human-validated source.**
**Refuted:** arxiv 1806.04212 (curiosity classifier); Argyle 2023 (algorithmic fidelity / effective proxy).
