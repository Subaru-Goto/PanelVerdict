---
title: "Build the panel evaluation module"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [002-decide-vote-schema, 003-decide-panel-model-and-provider, 006-build-persona-pool]
assignee: null
status: open
---

## Goal

Turn a sampled panel into votes:

- render persona → system prompt via template (**Big Five via BFI-2-Expanded-style sentences, never numeric/Likert** — Huang et al. 2026),
- **shared-prefix** (instructions + variants) for prompt caching,
- **per-agent A/B order randomization** (position-bias defense — this is also the load-bearing guardrail),
- structured output per the 002 schema,
- run in batches (~25), returning votes + reasons + order labels.