---
title: "Content checks on LLM-written fields before persisting"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006d-interests-synthesis]
assignee: null
status: open
---

## Goal

Gate all LLM-written content (interests + any prose) before it is persisted. Three checks (from 001/006):

1. **Schema/type validation** against a controlled vocabulary + length limits — reject/regenerate on failure.
2. **Injection screening** — pool-poisoning defense, **shared with [013](013-guardrails-mvp.md)**.
3. **Anti-stereotype audit** — measure demographic→interest concentration; flag/regenerate over-concentrated slices. (Prompt-time constraints in 006d help; this statistical audit is what actually catches it.)

Design basis: [001](001-decide-persona-schema-and-seed.md), [006](006-build-persona-pool.md).

## Notes

- Validate at the **population/proportion level**, never per-persona (001) — the audit is aggregate.
