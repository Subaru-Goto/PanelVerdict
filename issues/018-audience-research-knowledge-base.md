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

Roughly 20 documents. Chunked at ~500 tokens that is a few hundred chunks.

**The embedding cost is unmeasured** — corrected 2026-08-03. This line previously read
*"single-digit cents, once"*, which had no derivation and contradicts
[040](040-vote-cache-read-window.md): *"No embedding cost is recorded in
`docs/research/`, so the size of that bill is unknown rather than small."* 040 is right,
and the honest statement is that nobody has measured what an embedding call costs here.
It is a **one-off** cost over a few hundred chunks, which is the part that matters for
deciding to build this; the figure itself should come from a `--dry-run` before anyone
budgets against it.

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

---

## Amendment: what the sprint review added (2026-08-03)

The review named this ticket's absence as the **single largest gap against the graded
requirement**, quoting §1: *"advanced RAG with query translation"*, *"standard document
retrieval with embeddings"*, *"chunking strategies and similarity search"*. Everything
above already answers the second and third. Two things it does not answer follow.

### The blocker nobody had noticed: the system prompt forbids exactly this

The reviewer's own examples are *"what makes a good headline?"* and *"how should I
interpret a credible interval?"* — and `analyst.py:81` currently routes those **away**
from any tool:

> *"Anything general — what a credible interval means, why a headline might land, what
> this method can and cannot show — you answer yourself, directly, **and do not reach for
> a tool at all**."*

That clause is not incidental. It is half of the two-kinds rule whose *other* half —
*"anything about THIS test comes from a tool every time: never from memory, never
estimated"* — is what stops the analyst inventing figures. The rule works because it
admits **no middle**.

So this ticket cannot ship as a tool addition alone. It needs the two-kinds rule
rewritten to license a third case: *general knowledge, retrieved and cited*. And the
hazard is precise — a loosely worded third clause becomes the loophole through which
*"the panel skewed young"* gets answered from the model's weights.

**[044](044-report-says-what-won-not-what-to-change.md) needs the same clause**, for its
suggestions, which are also neither test facts nor pure general knowledge. Whoever writes
it should write it once, for both. Recorded here because neither ticket knew about the
other.

Note this also *sharpens* the corpus's value rather than diminishing it: today an
un-retrieved general answer is unfalsifiable, and the whole point of the sources
requirement above is that a reader can check a claim. The prompt rule and the corpus want
the same thing; the rule just predates the means.

### Query translation: partly already shipped, partly [043](043-persona-search-embeds-the-wrong-shape.md)

§1's *"query translation"* is worth claiming precisely, because two different things in
this repo answer to that name:

| what | where | is it RAG-shaped? |
|---|---|---|
| natural language → a structured filter | `targeting.py` — a model emits `TargetRequest`, code resolves it to countries and bands | no, and deliberately: [017](017-representative-sampling.md) replaced retrieval with `WHERE` here |
| natural language → a better *search* string | [043](043-persona-search-embeds-the-wrong-shape.md) — HyDE, so the query is shaped like the corpus | yes |

For this corpus the HyDE argument applies **more** cleanly than it does to persona
summaries, and the reason is the asymmetry 043 describes: a customer question is
interrogative, and these documents are expository prose with findings and β values. So
the same technique that 043 proposes for personas — have the model write the passage it
expects to find, then embed that — is the natural query-translation step here, and it
costs no extra call once retrieval is a tool the model already invokes with an argument.

### The LangChain surface the reviewer suggested, costed

> *"LangChain's `create_retrieval_chain` or a retriever tool with `VectorStoreRetriever`
> would integrate naturally alongside the existing tools."*

True, and it is not free. Both are **MISSING** from the environment:

```
langchain_postgres   MISSING
langchain_community  MISSING
```

So a `PGVector` vector store means a new dependency, against the rule that only packages
the project directly needs get added. And it would be the **first** retrieval in this
codebase not written as a plain SQL function — `nearest_panelists` is 8 lines of SQL with
a comment about the index opclass, and that is legible in a way a `VectorStoreRetriever`
is not.

**Open, not decided — the implementer's call, with both costs on the table.** The author
has since noted (2026-08-03) that the LangChain primitives are fair game where they
genuinely fit, so this is a trade-off to argue rather than a default to inherit:

| | SQL retrieval function | `VectorStoreRetriever` over `PGVector` |
|---|---|---|
| dependency | none | `langchain-postgres`, new |
| idiom | matches `nearest_panelists` — 8 lines of SQL, one comment about the index opclass | the first retrieval here not written as SQL |
| §1 | satisfied — the requirement asks for document retrieval with embeddings and similarity search, not a named abstraction | satisfied |
| buys | full control of the filter-plus-rank query, which the corpus will need for source filtering | chunking/loader plumbing and a retriever interface the chat loop can consume directly |

The SQL function is the smaller step and the one already written into Scope above. The
retriever is worth it if the loader and splitter machinery would otherwise be
hand-rolled — which is a real possibility here, since heading-aware chunking is a
decision this ticket already has to make.

Either way, **write the choice down rather than leaving a silence**, because *"why not
the framework's retriever?"* is a fair thing for a reviewer to ask twice.

## Done when

Added 2026-08-03 — this ticket predates the convention, and it is now the README's first
"Next steps" row, so it should say what finishing it means.

The analyst can be asked a general question — *"what does research say about
second-person pronouns?"* — and answer from **retrieved passages with their sources
shown**, not from its own weights. Which requires all of:

- a chunk table separate from `personas`, populated by a drop-and-reseed, with the
  heading-aware splitting decided above
- a retrieval function returning chunks **with citations**, exposed to the analyst
- the two-kinds rule in `analyst.py` rewritten to license *general knowledge, retrieved
  and cited* — the blocker in the amendment, and the clause
  [044](044-report-says-what-won-not-what-to-change.md) also needs
- a handful of question → expected-source pairs, enough to show retrieval finds the right
  document; a full faithfulness harness is not needed to ship
- votes still ungrounded, so every number 014 and 015 measured stays comparable
