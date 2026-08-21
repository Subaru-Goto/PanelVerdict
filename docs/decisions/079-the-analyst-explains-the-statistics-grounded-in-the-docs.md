---
title: "The analyst explains the statistics — grounded in the methodology docs, not vibes"
labels: [wayfinder:task]
parent: 078-map-next-chapter
blocked_by: []
assignee: subaru.dayo@gmail.com
status: closed
---

## Closed duplicate (2026-08-21)

[018](https://github.com/Subaru-Goto/PanelVerdict/issues/124) already specifies this ticket's goal in
far greater depth — it was rewritten on 2026-08-04 into exactly the
how-to-read-this-report knowledge base, with the concepts-never-figures rule,
heading-aware chunking, the two-kinds routing fix, and judged answer quality. This
ticket was drafted against the maps' **stale description** of 018 (the killed
audience-research corpus). Its two genuine additions — hybrid `tsvector`+pgvector
retrieval, and the GraphRAG considered-and-declined verdict — were folded into 018's
2026-08-21 addendum, which now carries the RAG requirement on
[078-map-next-chapter](https://github.com/Subaru-Goto/PanelVerdict/issues/122).

## Goal (as originally posed)

Asked *"what is a credible interval?"*, *"what does ROPE mean?"*, or *"how was this
verdict calculated?"*, the analyst answers from a retrieved passage of this repo's own
methodology docs, with a citation — never from the model's general prior. This is the
**unstructured half of the RAG requirement** (author's framing, 2026-08-21; the
structured half is the persona pool the panel already retrieves from).

## Why the corpus is already written

`docs/reading-the-posterior.md` (273 lines) exists precisely to explain the posterior to
a reader; `docs/research/adaptive-stopping.md` explains why an early stop is sound; the
report's cold-read-iterated captions define every number's meaning. Nothing needs
authoring — only chunking, embedding, and serving. Being **self-authored**, the corpus
adds no untrusted-text surface (`least-privilege.md`'s discipline holds without new
nonce-work).

## Scope

- Chunk + embed the methodology corpus into a pgvector table (the embedder and
  `init_embeddings` path exist); consult `/langchain-rag` for the splitter/store shape.
- A new read-only analyst tool (`explain_methodology`), LLM-decides-when /
  code-decides-how like the existing three; answers carry the source section. `ToolDeps`
  stays spend-free.
- **Hybrid retrieval from the start:** these queries are exact jargon — "HDI", "ROPE",
  "Beta-Binomial" — where sparse keyword match beats embeddings. Postgres `tsvector` +
  pgvector cosine, fused (reciprocal-rank), all in SQL; near-free at this corpus size.
  (Author asked about hybrid RAG, 2026-08-21 — this is where it earns its place.)
- A small golden set (question → expected doc section) so retrieval quality is asserted,
  not assumed — the corpus is tiny, so this is cheap.
- Prompt line: definitional/methodology questions go through the tool; the existing
  "answer only from tool results" discipline then grounds them for free.

## Considered and declined, so it is not reopened from enthusiasm

**GraphRAG** (entity-graph extraction, community summaries, multi-hop traversal): built
for large, entity-rich corpora where relationships span documents. This corpus is ~4k
lines of self-authored explanation and the questions are definitional — chunk retrieval
answers them. The LLM-extraction index would cost more than the corpus is worth. The one
place it could earn a look is [018](https://github.com/Subaru-Goto/PanelVerdict/issues/124)'s
audience-research corpus, if the validation study ever ungates it — noted there, not
built here.

## Done when

The three example questions above return doc-grounded, cited answers; the golden set
passes; a question the corpus cannot answer is said to be unanswerable rather than
improvised; and a paid run's report can be explained end to end from the dock.
