---
title: "Content checks on LLM-written fields before persisting"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006d-interests-synthesis]
assignee: null
status: done
---

## Goal

Gate all LLM-written content (interests + any prose) before it is persisted. Three checks (from 001/006):

1. **Schema/type validation** against a controlled vocabulary + length limits — reject/regenerate on failure.
2. **Injection screening** — pool-poisoning defense, **shared with [013](013-guardrails-mvp.md)**.
3. **Anti-stereotype audit** — measure demographic→interest concentration; flag/regenerate over-concentrated slices. (Prompt-time constraints in 006d help; this statistical audit is what actually catches it.)

Design basis: [001](001-decide-persona-schema-and-seed.md), [006](006-build-persona-pool.md).

## Notes

- Validate at the **population/proportion level**, never per-persona (001) — the audit is aggregate.

## Resolved (2026-07-23 grill) — design

The flat "three checks" framing collapses after 006d — two of the three are nearly hollow, so 006e's real substance is the **audit** and the **plausibility eval**, plus a thin injection denylist.

- **D1 — Validation is already done (006d).** `app.interests._validate` enforces count/length/format, and we chose *open* vocab (006d D1) — there is no closed vocabulary to check against. 006e adds nothing here.
- **D2 — Injection: thin local denylist only; toxicity + external API deferred to 013.** No untrusted input feeds offline interest generation (the prompt carries only our own sampled demographics + Big Five), and 006d's format allowlist + 40-char cap already strip punctuation/URLs. The one residual path: a plain-word imperative (e.g. "ignore all previous instructions", 32 chars, passes the allowlist) getting rendered into the **panel prompt** at vote time. A small denylist for instruction-like phrases catches that. Moderation APIs (Mistral/OpenAI) target *toxicity*, not injection, so they're the wrong tool here and belong at 013's runtime boundary where untrusted variants/target-descriptions actually enter. **Nonce-delimiting** of interpolated content (variants + interests) is owned by [013](013-guardrails-mvp.md), designed once — not piecemeal here (a static XML tag is forgeable; a per-request nonce isn't).
- **D3 — Anti-stereotype audit: cluster-free cosine dispersion, numpy-only.** Measure interest **variance collapse** per demographic variable **separately** (marginals — joint cells are too sparse at 5k; *known limitation:* misses interaction stereotypes like "young Japanese women", revisit at larger pool). *Converged during the grill:* rather than hard-cluster 1536-d vectors (density clustering breaks in high-d; PCA is the wrong reducer for embeddings; UMAP→HDBSCAN is the right stack but a heavy dep), the collapse KPI is **cluster-free** — within-group cosine **dispersion** (`1 − ‖mean-resultant‖` on unit-normalized, mean-centered vectors; robust at 1536-d, no reduction). A group far below the pool's dispersion has collapsed; culprit interests are named by frequency **exemplars** (no clustering) for the sparing regen. The **UMAP→HDBSCAN topic model** (named discovered categories) moves to **006g** as an exploration/dashboard feature. Data is the generated pool (006d), never a separate "ask the LLM for popular hobbies" call (that would be the closed taxonomy D1 rejected). Thresholds **tuned on the first dev pool**, passed in, not baked.
- **D4 — Control philosophy: measure-first, correct only egregious collapse, report the rest.** Over-control is the worse failure and it *hides* (a massaged pool looks pristine but is a fiction that erased true base rates). So we **never target zero MI** (demographic→interest correlation is real and desirable); the stopping condition is "no group is a caricature," not "interests are demographically blind." Regeneration is conservative: fire only on egregious collapse, pass a targeted **`avoid` hint** to `synthesize_interests` (a small 006d interface addition), cap at 1–2 rounds, and **log residual concentration as a 006g QC finding** rather than grinding a slice to uniformity.
- **D5 — Composition.** 006e *flags* the over-concentrated `persona_id`s (+ what to avoid); [006f](006f-persistence.md) *drives* the regenerate loop; 006d *regenerates*; then re-embed → re-audit. 006e measures/flags; it does not orchestrate.
- **D6 — Plausibility G-Eval: thin custom (not DeepEval), sample-based QC.** An injected judge LLM scores a sampled persona's `(demographics + Big Five + interests)` on a short rubric (plausible for age/demographics? coherent as one individual? consistent with personality?) → structured `{score, reason}`. Runs **offline on a sample** (the ~200 dev subset or a random few-hundred). Primary output is an **aggregate pass-rate = a QC signal on generation-prompt health**, not a per-persona filter; a low rate means *iterate the prompt*, not regenerate individuals. Reuses the OpenRouter/LangChain layer (005); judge model configurable.

## Scope line

- **006e ships (as 3 small PRs):** (1) the thin injection denylist; (2) the anti-stereotype audit (embedding-cluster metric + per-slice flags + pool-level summary) and its flag→regenerate identification; (3) the plausibility G-Eval harness.
- **Depends on / touches:** a small `avoid` param on 006d's `synthesize_interests`; 013 owns nonce-delimiting (scope note added there).
- **Not 006e:** external moderation API + toxicity + nonce-delimiting (013); the regenerate-loop orchestration + persistence (006f); the QC dashboard rendering (006g) — 006e only *exposes the numbers* 006g displays.
