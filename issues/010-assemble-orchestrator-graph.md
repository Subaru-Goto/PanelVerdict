---
title: "Assemble the orchestrator graph (LangGraph)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [007-build-targeting-query-translation, 008-build-panel-evaluation, 009-build-bayesian-layer]
assignee: null
status: open
---

## Goal

Wire the real pieces into one LangGraph graph, replacing the tracer bullet's stubs:

parse target (007) → retrieve + sample personas → fan out panel batches (008) → update posterior (009) → **adaptive-stopping conditional edge** back to fan-out → aggregate & build the report payload (winner, posterior).

**Amended 2026-07-26 ([007](007-build-targeting-query-translation.md)):** the payload's "segment breakdown target vs. control" is dropped — a production panel is one target group and the posterior is read off it. Controls live in the testing track, not the product path.

Gap-fill persona generation is **fog** (see map Notes) — do not build it here unless the frontier has graduated it.