---
title: "Build the 'Ask the analyst' chatbot + tools (chatbot requirement)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [010-assemble-orchestrator-graph, 011-build-report-ui]
assignee: null
status: open
---

## Goal

The chatbot + tool-calling requirement, embedded in the report and **scoped to the current test**:

- ≥3 tools (LLM decides *when*, deterministic code does *how*): `run_panel_test`, `search_personas`, `analyze_results` (+ optional `estimate_cost` / `get_test_history`),
- **suggested-question chips** rather than free composition (each chip maps to a requirement and demos reliably).

The exact chip set is fog until this ticket is worked (see map Notes).
