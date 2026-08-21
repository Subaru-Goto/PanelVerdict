---
title: "Tracer bullet: 2 headlines → fixed panel → naive verdict, end to end"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [002-decide-vote-schema, 003-decide-panel-model-and-provider, 004-standup-skeleton-infra]
assignee: subaru
status: closed
---

## Goal

Kill integration risk early with a thin end-to-end slice **using stubs**:

- 2 hardcoded headlines in,
- a tiny **fixed** panel (e.g. 5 hardcoded personas — no pool, no retrieval),
- real LLM votes using the 002 schema,
- a **naive count** verdict (no Bayesian yet),
- rendered in a minimal Next.js page via the API.

No targeting, no real pool, no posterior. Goal is proving the wires connect, not correctness of the verdict.

## Done (2026-07-19, PR #7)

Shipped end to end: `POST /evaluate` runs `FIXED_PANEL` → real `gpt-5-mini` votes (002 schema) → counterbalanced position→id resolution → naive-count verdict, rendered in the Next.js page. Verified with a real model run in the browser.

Surfaced two integration findings (recorded in the decision docs): the LLM layer standardised on LangChain, and `gpt-5-mini` rejects a custom `temperature` (→ 002/003 reproducibility amendments). Cost/robustness items (prompt caching, spend-cap/402 handling) consciously deferred to 008; reason-quality eval to 006 (needs real personas).