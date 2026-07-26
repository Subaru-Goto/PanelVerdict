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
- panel sampling: 100–300 personas, **all target-matched** (see the control-group amendment below),
- **fixed seed** → reproducible panels.

## Amended 2026-07-26 — no control group in a production panel

The panel was specified as ~80–90% target-matched plus a 10–20% random control.
**Dropped: a production panel is one target group, and the Bayesian layer reads the
preference off it.** Controls belong to the testing track — 014's harness — not to
the product path.

The reason is that the control changes no decision the customer makes. If B wins
70/30 in the target and also 70/30 in a random panel, the recommendation is still
"ship B"; the control only annotates the verdict, it never redirects it. Meanwhile
it costs: those 20–40 votes come out of the target group and widen the credible
interval on the number actually reported, and at 10–20% of a panel the control's own
preference is pinned only to roughly ±22 points, so it is a blunt annotation at that.

Two distinctions that were being conflated:

- **Validation control vs. per-test control.** The grounding research endorses a
  control group *for isolating targeting effects*, and [001](001-decide-persona-schema-and-seed.md)
  cites it. That is a one-off experiment, already answered at the mechanism level by
  [014](014-targeting-manipulation-check.md) (32.5% of votes move against an ~11%
  noise floor), with the full version — the Upworthy study — out of scope on the map.
  A control in *every* customer test is a weaker rerun of a check already done
  properly.
- **The useful comparison is segment vs. segment, not target vs. noise.** "Should I
  write different copy per audience?" is answered by comparing two target segments,
  which is a product feature worth building deliberately if wanted. Comparing a
  target against random strangers answers almost nothing, imprecisely.

Knock-on: [009](009-build-bayesian-layer.md) fits one posterior rather than two;
[010](010-assemble-orchestrator-graph.md)'s report payload drops its "segment
breakdown target vs. control"; [002](002-decide-vote-schema.md) is untouched, since
`VoteRecord` needs no matched/control label. No `control_fraction` parameter either
— an unused knob in product code is generality with prose for a justification, and
`experiments/` is where controls live.

## Amended 2026-07-26 — `culture_tag` lives in code, and here is when that flips

The ladder below assumes a stored `culture_tag`. There isn't one: 006b never added
it, and `schema.sql` carries only country. **For v1 it stays in code** — the tag is
a pure function of country (US/DE → Western, JP → Asian), so a column would be a
denormalised copy that can drift from what it derives from, and at three countries
the mapping is three lines. The middle rung is `WHERE country IN (…)`.

**The trigger for moving it into the database is not "many countries" —
it is countries becoming *data* rather than *code*.** `Locale` is a Python enum, so
today adding a country already requires a deploy and the tag can ride along in the
same commit. The moment the country list comes from a table, so a country can be
seeded without deploying, the tag has to follow it there or the two silently
disagree. Note what is *not* a reason: `country IN (…)` does not degrade with more
countries — the list is bounded by the country count and Postgres handles that
trivially. Moving it for performance would be moving it for the wrong reason.

Two things to get right whenever that day comes: the tag belongs on a `countries`
table keyed by country, **not** repeated on every persona row (one row per country,
not per person), and the coarse-tag vocabulary itself needs a source — "Asian /
Western" is a v1 convenience that 001 already flagged as not a census category, and
it will not survive a long country list without one.

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