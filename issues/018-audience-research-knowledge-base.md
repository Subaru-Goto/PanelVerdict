---
title: "Audience-research knowledge base: the RAG the analyst actually needs"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Goal

A small corpus of audience and copy research — chunked, embedded, similarity-searched —
that the analyst retrieves from when explaining a verdict, **with sources shown**.

Re-scoped **into** v1 on 2026-07-27. The map had ruled it out with the reasoning *"the
RAG requirement itself is already met by persona-pool retrieval, so this corpus is a
value-add, not a requirement."* [017](017-representative-sampling.md) invalidates that
premise: persona retrieval now runs on SQL columns, which is the right engineering and
leaves the corpus as the only place embeddings do work no `WHERE` clause could.

## Why this is the honest RAG here

Retrieval over structured columns invites the fair objection *"that's just SQL."* This
corpus does not:

> *"What does published research say about second-person pronouns in headlines?"*

There is no column for that. The answer lives in prose, spread across documents, and
finding the relevant passage **is** a similarity search. That is what the requirement is
asking for, and this is the part of the system where it is true.

## The corpus already exists

No new sourcing needed — every document is one this project has already read and cited:

| source | what it grounds |
|---|---|
| Gligorić, Lifchits, West & Anderson 2023 (PLOS ONE) — 24,333 Upworthy A/B pairs, 12 pre-registered hypotheses | which copy levers move real clicks, and which do not |
| Aubin Le Quéré & Matias 2025 (Sci Rep) — 8,977 tests, curvilinear concreteness | why "more concrete" is not monotonically better |
| Han et al. 2025 — persona injection moves self-reported traits but not behaviour | the failure mode our panel was checked against |
| `docs/research/manipulation-check.md` (014) | our own measured trait effects |
| `docs/research/task-framing.md` (015) | our own measured framing effects and the failed validity check |
| `docs/lessons-so-far.md` | the synthesis, including the two headline findings |

Roughly 20 documents. Chunked at ~500 tokens that is a few hundred chunks — **embedding
cost is single-digit cents, once.**

## The demo this unlocks, which is the real argument for it

Our own write-ups sit in the same index as the published field data. So the analyst can
be asked *"how confident should I be?"* about a `you`-pronoun test and retrieve **both**:

- Gligorić: second-person pronouns showed **no detectable effect** across 24,333 real A/B
  tests (β +0.051, hypothesis rejected)
- our 015 run: the panel preferred the *"you"* variant **0.82 / 0.90 / 0.94**

An analyst that surfaces that contradiction, with both sources cited, is doing something
genuinely useful — and it is the honest presentation of a system we know is unvalidated on
same-meaning copy. It turns [015](015-task-framing-sensitivity.md)'s negative result from
a caveat buried in a doc into a feature of the product.

## Scope

- **New table**, one row per chunk: text, source, section/locator, embedding. Separate
  from `personas`; do not overload `summary_embedding`.
- **Reuse what exists**: `OpenRouterEmbedder`, `prepare_connection`, the `schema.sql` +
  `apply_schema` pattern, and the drop-and-reseed convention (a corpus is a cache of the
  committed documents, so no migrations — same reasoning as [006j](006j-persona-summary-embedding.md) D6).
- **A retrieval function** returning chunks with their sources. That is this ticket's
  deliverable; wiring it into the chat loop belongs to
  [012](012-build-analyst-chatbot-tools.md).
- **Sources are not optional.** Every retrieved snippet carries its citation through to
  the answer. It is a graded requirement, it is the anti-hallucination measure, and it is
  the only way a reader can check a claim about a study.

## Decisions this ticket has to make

**Chunking.** Fixed-size with overlap is the default, but these documents are
section-structured markdown and papers with abstracts and findings sections. Splitting on
headings keeps a finding with its numbers; fixed windows can cut a β from its hypothesis.
Prefer heading-aware, fall back to fixed windows inside an over-long section.

**What retrieval is allowed to touch — and this one matters.** `project-idea.md:158`
says retrieved snippets *"ground agent votes and the analyst's explanations."*

**Restrict v1 to the analyst's explanations. Do not ground the votes.** Injecting
research into the vote prompt changes what the panel *is*, which would invalidate every
number 014 and 015 measured against the current prompt, and 015 already showed the
verdict is sensitive to the wording of the question alone. Vote grounding is a real
experiment — it is the ablation the out-of-scope Upworthy study was going to run — and it
needs its own before/after measurement, not a quiet prompt change.

**Retrieval quality measurement.** Unlike the persona pool, this corpus has **no
ground-truth relevance labels** — which is exactly where judge-based tooling (RAGAS,
DeepEval) earns its place, having been the wrong tool for
[016](016-translation-accuracy-golden-set.md) and 017. A handful of question → expected-source
pairs is probably enough for v1; a full faithfulness harness is not needed to ship.

## Security note

The corpus is **trusted input** — we choose every document, and it is committed, not
user-supplied. So the retrieved text is not an injection vector in the way a user-supplied
document would be. That property is worth stating in [013](013-guardrails-mvp.md) rather
than assumed, because it stops holding the moment anyone can upload a source.
