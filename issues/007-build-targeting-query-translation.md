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

## Amended 2026-07-26 — `culture_tag` is not a column, and should not become one

The ladder below assumes a stored `culture_tag`. There isn't one: 006b never added
it, and `schema.sql` carries only country. Nor should it — the tag is a pure
function of country (US/DE → Western, JP → Asian), so storing it would be a
denormalised copy that can drift from the column it derives from. The middle rung
is `WHERE country IN (…)` with the mapping held in code.

Unblocked 2026-07-26: 006 closed with 006g.

## Region coverage + fallback (from the 2026-07-21 grounding grill; see [001](001-decide-persona-schema-and-seed.md) amendment)

The pool is **country-grounded** with a derived **`culture_tag`** (Asian/Western). v1 seeds JP/US/DE. **Coverage = the seed list**, so query translation must handle out-of-coverage targets:

- **Graceful degradation ladder:** `country → culture_tag → (global)`. e.g. a "China" target has no seeded country → fall back to `culture_tag = Asian` (currently only Japan is seeded).

## Amended 2026-07-26 — what the vector half now carries

[006j](006j-persona-summary-embedding.md) makes the fuzzy half a single
`personas.summary_embedding` over a templated summary of **demographics + Big
Five**. Mechanism unchanged (hybrid: SQL for hard attributes, vector for fuzzy);
coverage narrower:

- **In coverage:** dispositional and demographic targets — *"cautious,
  budget-conscious homeowners in their 40s"* maps onto neuroticism,
  conscientiousness, income quintile and age.
- **Out of coverage:** activity or lifestyle targets — *"outdoorsy people"*,
  *"gamers"*. Personas carry no interest or leisure field
  ([006i](006i-leisure-profiles.md) closed; [006d](006d-interests-synthesis.md)
  superseded), so nothing can match.

An out-of-coverage *attribute* must be surfaced the same way an out-of-coverage
*region* is — **never silently answered** with a panel matched on the remaining
words of the query, which would look like a targeted panel and be a random one.
- **Never silent.** Every fallback must be **surfaced to the user** — e.g. *"No China data; approximating with Asian-region personas (currently Japan only). Treat as indicative."* Silent substitution risks false confidence, and Japan is a weak proxy for China (different demographics/interests/language).
- Empty result is an honest outcome when even the coarse tag has no seeded coverage — report it, don't fabricate a panel.