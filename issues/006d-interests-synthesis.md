---
title: "Interests synthesis: LLM-generate under anti-stereotype constraints + embed"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006b-demographics-sampler, 006c-bigfive-sampler]
assignee: null
status: open
---

## Goal

Synthesize the **interests** field — the one un-groundable field (001) — with the LLM, under **anti-stereotype constraints**, conditioned on the persona's already-sampled demographics + Big Five. Compute **embeddings** for fuzzy targeting and persist them.

Design basis: [001](001-decide-persona-schema-and-seed.md), [006](006-build-persona-pool.md).

## In scope

- Batched LLM generation of interests, anti-stereotype constraints in the prompt.
- Embeddings via OpenRouter (langchain `OpenAIEmbeddings`, `openai/text-embedding-3-small`) — the model layer standardised on LangChain in 005.
- Controlled vocabulary + length limits enforced at generation time (statistical anti-stereotype audit itself is 006e).

## Notes

- Interests are a **stereotype hotspot** (001) — prompt-time constraints help, but the statistical audit in 006e is what catches over-concentration.

## Resolved (2026-07-23 grill) — design

- **D1 — Vocabulary: open validated short tags, not a closed taxonomy.** 001's "no free text persisted" is read as "no prose" — a short, screened noun-phrase is a typed value. A closed enum would collapse the field into categorical selection and make the embeddings decorative.
- **D2 — Plausibility from the LLM prior, no hardcoded rules.** Condition on demographics (country included) + Big Five and trust the model's latent base rates (Australia→surfing). Big Five *legitimizes the tail* — a rare interest (an 85-year-old snowboarder) lands on the right personality (high O/E, low N). No hand-coded plausibility gate; 006e's statistical audit is the backstop, tuned to catch **variance collapse** (80% of a group share one interest) not mere correlation (a mild, true base rate is desirable).
- **D3 — Categorization: specific at generation, grouping emergent.** Generate `"snowboarding"`, never `"extreme sports"` — prompt fidelity + realism. Grouping for the audit comes from **per-interest embedding clusters** (006e); no hand-built taxonomy (that would be speculative generality), deferred unless clusters prove opaque.
- **D4 — Embeddings: OpenRouter + `openai/text-embedding-3-small` (1536-dim), per-interest vectors.** Empirically verified OpenRouter serves `/embeddings` (its FAQ only advertises chat). One vector **per interest** is the stored primitive (the audit clusters individual hobbies); mean-pool for persona-level fuzzy targeting. `embedding_model` added to `Settings`.
- **D5 — Generation shape: single-persona, iid.** Multi-persona-per-prompt makes the model self-balance interests across the batch, breaking the independence the 006e population audit depends on (and making batch size a hidden distribution parameter). Each persona is an independent draw → observed frequencies are an unbiased estimate of `P(interests | persona)`. "Batched" = **concurrency** at the 006f seed-script layer, not multiple personas in one prompt. (Embedding *can* be batched — independent per input.)
- **D6 — Determinism: inject LLM + embedder (Protocols); interests frozen by 006f.** Numeric fields stay seed-reproducible (006b/006c); the LLM field can't be, so 006f idempotency (keyed by persona id) freezes it. Tests stub the injected dependencies — no network.
- **D7 — Eval: thin custom G-Eval, offline on a sample** (LLM-judge plausibility rubric over the existing LangChain layer — not DeepEval, per minimal-deps). The statistical concentration audit (numpy) is 006e. Both feed batch-regeneration.

## Scope line

- **006d ships:** single-persona `synthesize_interests` (injected `InterestLLM`, structured output, bounded regenerate-on-invalid loop), cheap generation-time validators (count / per-tag length / format allowlist), `embed_interests` (injected `Embedder`, per-interest vectors), the anti-stereotype prompt, and persona assembly. Concrete OpenRouter adapters live in `app.llm`.
- **Not 006d:** injection screen + statistical audit + quality-eval gate (006e); persistence / pgvector / idempotent seed script + concurrency (006f).
