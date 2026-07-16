---
title: "Decide panel model + OpenRouter provider config"
labels: [wayfinder:research]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Question

Which **single cheap model** (Haiku / 4o-mini / Gemini Flash class) via OpenRouter for the v1 panel, and what provider config?

Verify (current pricing/limits — don't trust memory):
- prompt-caching availability through OpenRouter for the chosen model (the shared instructions+variants prefix is the main cost lever),
- structured-output / forced-function-call support,
- per-key **spend cap** as a hard budget brake.
- **trait-enactment fidelity on the cheap model** — Big Five enactment is model-dependent (frontier models ≫ GPT-3.5; Huang et al. 2026). Verify the chosen cheap model actually enacts Big Five (the manipulation check will also expose this); personality fidelity is a selection criterion, not just cost.

Rule: pick ONE consistent model and never mix models within a run.

**Answer records:** the chosen model id, the provider config, and the spend cap set.