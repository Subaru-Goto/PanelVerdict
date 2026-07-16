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

Rule: pick ONE consistent model and never mix models within a run.

**Answer records:** the chosen model id, the provider config, and the spend cap set.