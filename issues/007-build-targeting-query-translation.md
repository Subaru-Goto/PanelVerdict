---
title: "Build hybrid targeting / query translation (the RAG requirement)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [006-build-persona-pool]
assignee: null
status: open
---

## Goal

Natural-language target description → **structured SQL filters + embedding query** (self-query / query translation — this IS the "advanced RAG" requirement).

- hybrid retrieval: SQL for hard attributes, vector for fuzzy attributes,
- panel sampling: 100–300 personas, ~80–90% target-matched + 10–20% random **control group**,
- **fixed seed** → reproducible panels.

## Region coverage + fallback (from the 2026-07-21 grounding grill; see [001](001-decide-persona-schema-and-seed.md) amendment)

The pool is **country-grounded** with a derived **`culture_tag`** (Asian/Western). v1 seeds JP/US/DE. **Coverage = the seed list**, so query translation must handle out-of-coverage targets:

- **Graceful degradation ladder:** `country → culture_tag → (global)`. e.g. a "China" target has no seeded country → fall back to `culture_tag = Asian` (currently only Japan is seeded).
- **Never silent.** Every fallback must be **surfaced to the user** — e.g. *"No China data; approximating with Asian-region personas (currently Japan only). Treat as indicative."* Silent substitution risks false confidence, and Japan is a weak proxy for China (different demographics/interests/language).
- Empty result is an honest outcome when even the coarse tag has no seeded coverage — report it, don't fabricate a panel.