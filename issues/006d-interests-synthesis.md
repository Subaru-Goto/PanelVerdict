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
