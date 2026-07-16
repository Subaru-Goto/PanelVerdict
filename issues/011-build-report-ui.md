---
title: "Build the report UI (Next.js)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [009-build-bayesian-layer, 010-assemble-orchestrator-graph]
assignee: null
status: open
---

## Goal

The report dashboard:

- vote split, posterior plot (P(B>A), lift + CrI), ROPE verdict,
- segment breakdown (target vs. control group),
- reason list (reason *clustering* is fog — see map Notes),
- **live batch-streaming progress** ("87/200 personas voted…") over SSE,
- **all model output rendered as plain text** (exfiltration-markup defense — never `dangerouslySetInnerHTML` on model output).
