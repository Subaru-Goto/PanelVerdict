---
title: "Decide the panel vote + structured-output schema"
labels: [wayfinder:grilling]
parent: 000-map
blocked_by: []
assignee: subaru
status: closed
---

## Question

Define the panel agent's structured output. The vote is a **preference/choice** between the two variants (or neither) — "click" is just the headline instantiation; for a design/image the same choice surfaces as "which would you pick".

- **Vote enum** — decision leans **3-way {A, B, neither}** (prefer A / prefer B / would choose neither) for forward-compat with the zero-inflated model (see map Notes + `docs/project-idea.md`). Confirm.
- **Reason** — a 1-line rationale field.
- **Order field** — which variant was shown first (needed to audit / correct position bias).

Confirm the v1 treatment: the neither-rate is **reported descriptively but NOT modeled** — the Beta-Binomial runs over those who chose A or B only. Lock the exact JSON/enum shape the panel and the Bayesian layer both depend on.

**Answer records:** the final structured-output schema.

---

## Resolution (2026-07-17)

### Model structured output (what the panel agent emits)

```json
{
  "chosen": "option_1" | "option_2",
  "reason": "<1-line, content-based rationale>"
}
```

- **Forced binary — no `neither` in v1.** Every persona picks one option. Rationale: matches the flat-prior Beta-Binomial scope (zero-inflation is B-era); LLMs are reliable at *comparative* choice but poorly calibrated on absolute "would I click"; and `neither` is semantically overloaded (indifference vs. rejection vs. out-of-audience). The "both variants are weak" signal is recovered from `reason`, not from an enum.
- **Positional + identity-blind.** The model sees two neutrally-labelled options in a counterbalanced order and never sees which is "A". This is what makes position bias measurable/correctable (swap-and-average; Wang et al. 2023). The prompt asks for **content-based** reasons (not "the first one") so rationales are self-contained.

### Persisted vote record (what the system stores)

```json
{
  "persona_id": "<id>",
  "test_id": "<id>",
  "chosen_variant_id": "<id>",
  "presentation_order": ["<variant_id>", "<variant_id>"],
  "reason": "<text>"
}
```

- **Choice as a variant *reference*** (`chosen_variant_id`), not a literal `A`/`B` — forward-compatible to **multivariate (v2)** with no schema change (`presentation_order` becomes an N-list). All v1 logic stays strictly 2-variant.
- The system owns order randomisation + the position→id mapping; identity is re-attached at persist time, so the analyst always works on fully-identified records. `presentation_order` is **system metadata, not model output.**

### Position policy

- Order **randomised and stored per vote**; overall **50/50 counterbalanced** (deterministic — removes top-line position drift for free).
- Pure randomisation is adequate for the top-line and large slices (n≈200 → ~7% max drift). **Stratified counterbalancing / minimisation (Pocock–Simon)** is the documented fallback — built only if small-segment reporting becomes a feature *and* position leakage is observed; exact strata graduate with the targeting design ([007](007-build-targeting-query-translation.md)).
- **Residual position bias is measured per model** — a selection criterion for [003](003-decide-panel-model-and-provider.md).

### Bayesian treatment

- Flat-prior **Beta-Binomial over `chosen_variant_id`** (all voters; no zero-inflation). There is no `neither`-rate in v1.

### Reproducibility (test-retest reliability)

- Re-running the same test must yield ~the same verdict. **Variance comes from the seeded, reproducible persona population ([001](001-decide-persona-schema-and-seed.md)), not from decoding:** temperature ≈ 0 → each persona's vote is (near-)deterministic; the panel's spread comes from population heterogeneity, which is reproducible.
- **Pin the model version + provider** ([003](003-decide-panel-model-and-provider.md)) — silent model updates would drift results.
- Deterministic, stored order removes order as a variance source.
- Residual provider/hardware non-determinism → *almost*, not bit-identical; **test-retest agreement is a QA metric**. Optional **vote caching** keyed on `(persona, test, order)` gives exact reproducibility + cost savings, invalidated when any input changes.

**Two reproducibility axes (both required):**

1. **Test-retest — *same* panel, re-run** → near-identical (temp≈0 + pinned model + stored order, above). Owned by the vote/execution layer.
2. **Sample-stability — a *different* persona sample from the pool, same target** → verdicts should agree **within their credible intervals**. Owned by the *sampling* + *Bayesian* layers: draw panels representatively/stratified to the target so draws are comparable ([006](006-build-persona-pool.md)/[007](007-build-targeting-query-translation.md)); rely on sample size + **adaptive stopping** ([009](009-build-bayesian-layer.md)). **Key nuance:** when A≈B (true effect ≈ 0), different samples *should* sometimes disagree on the winner — that is correct, and the Beta-Binomial reports it as low `P(B>A)` / wide CrI rather than a false-confident flip. "Similar" means *agree within stated uncertainty*, not identical point estimates. **Sample-stability (bootstrap agreement across resampled panels) is a QA metric.**

### Downstream couplings

- Model-version pinning + position-bias magnitude → **003**.
- Vote caching + test-retest QA metric → orchestration (**005** / **008**).
- Representative panel sampling + sample-stability QA → **006** / **007** / **008**; adaptive stopping → **009**.
- Exact stratification dimensions → **007**.

## Amendment (2026-07-19) — `temperature≈0` is unavailable for the chosen model

The v1 panel model `openai/gpt-5-mini` ([003](003-decide-panel-model-and-provider.md)) rejects any non-default `temperature` (HTTP 400; GPT-5 reasoning models fix it at 1). So the "temperature ≈ 0 → each persona's vote is (near-)deterministic" assumption in the Reproducibility section above **does not hold** — per-persona votes carry sampling variance.

Determinism instead rests on:
1. the **seeded, reproducible population** — already the *primary* variance source, unchanged;
2. best-effort **`seed`** (if supported by the model/provider); and
3. **per-vote caching** keyed on `(persona, test, order)` (008) for exact replay.

Test-retest agreement remains a **QA metric** (as already noted — "almost, not bit-identical"), just with a wider band. If exact per-vote reproducibility ever becomes a hard requirement, that converts into a model-selection constraint (prefer a model that supports `temperature`/`seed`) → feeds [003](003-decide-panel-model-and-provider.md).