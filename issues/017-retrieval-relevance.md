---
title: "Retrieval relevance: does the vector half beat a random draw?"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Goal

Measure whether [007](007-build-targeting-query-translation.md)'s **vector half
actually earns its place**. The hard filters are verifiable by construction — a
country filter cannot return the wrong country. The open question is the ranking: when
a target asks for cautious people, does ordering by cosine over
`personas.summary_embedding` put genuinely high-neuroticism personas at the top, or
does it return something indistinguishable from a random draw?

Nobody has checked. `retrieve_panel`'s vector branch is tested for *mechanism* (nearest
first, ties broken on id) and never for *relevance*.

## Why RAGAS is the wrong instrument here too — and this is the interesting part

Context precision is the right *concept*. But RAGAS estimates it with an LLM judge,
because a normal document corpus has **no ground-truth relevance labels** — somebody
has to decide whether a retrieved chunk was relevant.

**Our corpus is synthetic and fully labelled.** Every persona's neuroticism is a float
in a Postgres column, and `bucketize` turns it into the exact level the query asked
for. So relevance is not a matter of opinion — it is a `WHERE` clause we deliberately
did not run.

That makes precision@k computable **exactly, for free, with no model call**:

> query asks `neuroticism=high` → of the 200 retrieved, what fraction actually
> bucketize to `high`?

Reaching for a judge to guess an answer we have in a column would be strictly worse:
slower, costly, and less accurate than the ground truth. Use RAGAS-style judging where
there is no label. Here there is.

## The measurement that matters: beat the baseline

Precision@k alone is not interpretable — if 38% of the pool is `medium` on every
trait (the population split 006c produces), then a random draw scores 38% on a
`medium` query and looks respectable. So the comparison is:

| arm | how |
|---|---|
| **vector** | `retrieve_panel` with the disposition embedding |
| **baseline** | same filters, same size, `md5(id, seed)` ordering — already implemented |

Report the **lift**: precision@k(vector) − precision@k(random). If the lift is ~0, the
embedding is decoration and the honest response is to say so in
[011](011-build-report-ui.md) rather than to describe the panel as dispositionally
matched.

## The specific reason to expect trouble

[006j](006j-persona-summary-embedding.md) embeds **one** vector per persona over
demographics **and** all five Big Five traits. A query rendered from one or two trait
phrases is a short string compared against a summary whose demographic prose
("A 42-year-old female living in the United States, who completed a university
degree…") is most of its length. That prose is constant-ish across the filtered set
but it is not nothing, and it may dominate the cosine.

Two consequences to measure separately:

- **Single-trait queries** — the common case. Most exposed to demographic dilution.
- **Multi-trait queries** — closer in shape to the embedded text, so plausibly better.
  If multi-trait works and single-trait does not, that is a finding with a fix
  (render the query as a full summary-shaped sentence), not just a null.

Also worth one cheap check: does the retrieved panel skew on traits **nobody asked
for**? One vector carries all five, so ranking on neuroticism may quietly sort by
openness too. That is the representativeness worry the map's panel-sampling fog item
holds, and this run can measure it at no extra cost.

## Scope

- ~10 queries: each trait alone at `high` and at `very_low`, plus two multi-trait ones.
- Per query: precision@k for vector and for the seeded-random baseline, at the panel
  size 010 will use (n=200) and at one small size, since a demo may draw fewer.
- Report per-trait, not pooled — a lift that exists for openness and not neuroticism is
  the useful shape, and 014 already found the traits behave differently.

## Cost

**Effectively zero.** The pool is already embedded; each query needs one
`text-embedding-3-small` call (~$0.00002) and the grading is SQL plus arithmetic. No
chat model, no judge. ~10 queries ≈ a fraction of a cent, against the $4 a vote sweep
costs.

Which is the argument for running it before [010](010-assemble-orchestrator-graph.md)
wires retrieval into the product: it is the cheapest measurement on the map and it can
invalidate a claim the report is about to make.

## What this does not cover

Whether the translator produced the right trait in the first place — that is
[016](016-translation-accuracy-golden-set.md). This ticket takes a `TargetQuery` as
given and asks only whether retrieval honours it.
