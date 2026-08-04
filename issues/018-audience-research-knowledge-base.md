---
title: "How-to-read-this-report knowledge base: the RAG the reader actually needs"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Goal

A small corpus — chunked, embedded, similarity-searched — that the analyst retrieves from
when a reader asks what something on the report *means*, **with sources shown**.

Two subjects, because two things on the report arrive with no explanation attached:

- **the Big Five**, as this product implements them
- **the Bayesian decision**, as this product implements it

Rewritten 2026-08-04. What changed and why is in [History](#history) — including the
corpus this ticket used to describe, and the argument that killed it.

## Why it is needed: the reader cannot read the source, and the model answers anyway

A customer has **no access to the code**. So when they ask what a trait level means, the
analyst answers from the model's own weights — and the model's most probable answers are
each wrong *about this product*:

| the likely answer | what this codebase does | source |
|---|---|---|
| scores come from a self-report inventory | sampled from `MVN(μ(age,gender), Σ)` — no panelist ever answered a questionnaire | `bigfive.py:33` |
| "high" means above average, or the top fifth | `HIGH` is +0.5σ to +1.5σ; `VERY_HIGH` is a separate band above it | `bigfive.py:57` |
| openness tracks education, culture, country | μ is conditioned on **age and gender only** — *"country does not condition the Big Five μ"* | `bigfive.py:17` |
| a textbook gloss of openness | the literal sentence that reached the vote prompt: *"curious and imaginative, drawn to new ideas and experiences"* | `panel.py:19` |

These are not obscure failure modes — they are the *default* completions. And the reader
cannot catch any of them. That is hallucination in the form that costs something: not
fabricated trivia, but a confident mismatch with what the system did, delivered to
somebody with no way to check it.

**A caution the same table has to obey.** `bigfive.py:58` warns that the cutoffs' clean
population shares — 6.7 / 24.2 / 38.3 / 24.2 / 6.7 — describe the *unconditional* normal;
*"a demographically conditioned cell skews off those shares, since μ moves with age and
gender."* A corpus document quoting the shares flat, for a panel drawn to quotas, would
commit this ticket's own defect while citing a source. Every seeded figure needs its
conditions attached.

## Why the prompt rule is the blocker, and it is misrouting rather than strictness

`analyst.py:78-84` sorts questions into two kinds: *about this test* (a tool, every time)
and *general* (answer from memory, `:81`). The rule works because it admits no middle.

**But "what does high openness mean" looks general and is not.** It is a fact about this
system's behaviour wearing the clothes of a psychology question, so the rule routes it to
memory *by design*. The routing is the defect; the missing corpus is only its other half.

Same for the statistics. *"Is a 0.95 credible interval good?"* reads general. *"Why is our
ROPE 0.43–0.57"* and *"why must the interval clear it entirely"* do not.

**The guard that has to survive the rewrite**, recorded 2026-08-03 and still binding: a
loosely worded third clause becomes the loophole through which *"the panel skewed young"*
gets answered from the model's weights. The new clause must license *this system's
documented mechanism, retrieved and cited* — narrow enough that a question about **this
run's** panel still goes to a tool. [044](044-report-says-what-won-not-what-to-change.md)
needs the same clause for its suggestions; whoever writes it should write it once.

## Why this is genuinely retrieval, stated without overclaiming

The old version of this ticket answered the fair objection *"that's just SQL"* by pointing
at published papers. That defence is gone with them, so the claim has to be re-made
honestly — and it splits:

- **Some questions are near-lookups.** *"What does high openness mean here?"* has one
  home. Retrieval is still the right mechanism, because the alternative is not a `WHERE`
  clause — there is no column for it — it is the model guessing. This is where the
  requirement is *thinly* met, and pretending otherwise would be the same overclaim the
  previous version made.
- **Some are genuinely multi-document.** *"B is ahead — why is this undecided?"* needs the
  ROPE's definition, why the interval must clear the band entirely, and what
  `detectable_gap` says at this panel size. Three documents, no single passage, and the
  answer has to be composed from prose. **That** is the similarity search earning its
  name.

So: the requirement is met by the *shape of the answer*, not by the corpus being exotic.
Write that down rather than restating the old paper argument, which no longer applies.

## What this corpus is not, and why

**No field research about how real people respond to copy.** It has no valid home here:

- **Not the analyst's.** The analyst explains what *this panel* did. The persona is what
  votes, so research about real human behaviour changes no output — it arrives after the
  verdict as commentary on it.
- **Not the vote's.** Grounding votes would change what the panel *is*, invalidating every
  number 014 and 015 measured — and 015 already showed the verdict is sensitive to the
  question's wording alone. That is a real experiment needing its own before/after
  measurement, not a quiet prompt change. It stays out of scope.
- **The validity question it speaks to is already answered elsewhere** — 015's negative
  result and the README's *Known limitations*, where a caveat about the whole method
  belongs. An analyst that volunteers *"field data disagrees with your report"* is not
  retrieval doing work; it is that caveat re-delivered by a chatbot, attached to the
  artifact the customer paid for.

**And so the corpus is entirely first-party**, which removes the redistribution question
and the only PDF (`docs/research/huang-et-al-*.pdf`) at once. Everything seeded is
committed markdown or a docstring, so the heading-aware splitter below covers all of it
with no loader dependency.

**Donnellan & Lucas (2008) still appears — as a citation, not a source.** Its BHPS and
GSOEP T-score tables are already *inside the product* as `bigfive_norms.json`, so the
document that explains where μ comes from cites the paper the way the code does.
`docs/research/donnellan-lucas-2008-table1.md` is the transcription it points to.

## Scope

- **New table**, one row per chunk: text, source, section/locator, embedding. Separate
  from `personas`; do not overload `summary_embedding`.
- **Reuse what exists**: `OpenRouterEmbedder`, `prepare_connection`, the `schema.sql` +
  `apply_schema` pattern, and drop-and-reseed (no migrations — a corpus is a cache of
  committed documents, same reasoning as [006j](006j-persona-summary-embedding.md) D6).
- **A retrieval function** returning chunks with their sources. That is this ticket's
  deliverable; wiring it into the chat loop belongs to
  [012](012-build-analyst-chatbot-tools.md).
- **Sources are not optional.** Every retrieved snippet carries its citation through to
  the answer. It is a graded requirement, it is the anti-hallucination measure, and it is
  the only way a reader can check a claim.

### What gets seeded

| subject | what the documents have to say | drawn from |
|---|---|---|
| trait meaning | the phrasing each level put in the vote prompt | `panel.py:19` `_TRAIT_PHRASES` |
| trait levels | half-sigma cutoffs, the shares they imply, **and that a quota-drawn cell skews off them** | `bigfive.py:57-59` |
| where μ comes from | conditioned on age and gender, not country; Donnellan & Lucas cited | `bigfive.py`, `docs/research/persona-seed-data.md` |
| measured trait effects | this project's own manipulation check | `docs/research/manipulation-check.md` |
| the decision rule | ROPE 0.43–0.57, why the interval must clear it, `credible_mass = 0.95`, HDI vs equal-tailed | `verdict.py` |
| why not MCMC | exact conjugate answer; sampling would break byte-identical replay | `verdict.py`, 010e |
| what the panel can resolve | `detectable_gap` — **±13.9 points at n=200**, in *posterior* share | `verdict.py:222`, [020](020-probability-not-label.md):113 |
| when it stops early | 2 confirmations, the 50-vote floor and its cost | `docs/research/adaptive-stopping.md` |

**The ±13.9 figure is exactly why this needs care.** 020 records that ±14 was a *rejected*
first pass expressing the gap as a raw vote share while every other number in the payload
lives in the posterior share. A corpus document that quoted ±14 would cite a figure this
repo already corrected away — and would do it authoritatively.

## Decisions this ticket has to make

**Chunking.** Fixed-size with overlap is the default, but these are section-structured
markdown documents. Splitting on headings keeps a claim with its number; fixed windows can
cut a figure from its condition — and the `bigfive.py:58` caveat above is precisely a
condition that must not be split from its shares. Prefer heading-aware, fall back to fixed
windows inside an over-long section.

**Hand-written prose versus generated from source — open.** Hand-written documents that
*cite* the constants, or documents generated from the constants themselves. This is not
decided here, and it is the decision the staleness hazard below turns on.

**Retrieval quality measurement.** No ground-truth relevance labels exist for this corpus,
which is where judge-based tooling (RAGAS, DeepEval) earns its place, having been the wrong
tool for [016](016-translation-accuracy-golden-set.md) and 017. A handful of
question → expected-source pairs is probably enough for v1; a full faithfulness harness is
not needed to ship.

## The hazard this design introduces

A corpus derived from source files **goes stale silently.** If `_TRAIT_PHRASES` or `_ROPE`
changes and nobody reseeds, the analyst cites a document confidently describing behaviour
the code no longer has — **strictly worse than answering from weights, because it arrives
with a citation.**

Drop-and-reseed is the mitigation, and it stops being mere convention here: it is
load-bearing once retrieved text makes claims about live constants. Whichever way the
hand-written/generated decision above goes, something has to fail when the corpus and the
code disagree.

## Security note

The corpus is **trusted input** — every document is chosen and committed, not
user-supplied, and now first-party throughout. So retrieved text is not an injection
vector the way an uploaded document would be. Worth stating in
[013](013-guardrails-mvp.md) rather than assumed, because it stops holding the moment
anyone can upload a source.

## History

Kept because the discarded arguments are the useful part.

- **Ruled out of v1 originally** — *"the RAG requirement is already met by persona-pool
  retrieval."* [017](017-representative-sampling.md) invalidated that: persona retrieval
  now runs on SQL columns, which is the right engineering and left embeddings with no work
  no `WHERE` clause could do.
- **Re-scoped in, 2026-07-27**, as ~20 documents of audience and copy research.
- **Named by the sprint review, 2026-08-03**, as the largest gap against §1's *"standard
  document retrieval with embeddings"*, *"chunking strategies and similarity search"*.
  Two findings from that pass survive above: the prompt-rule blocker, and that HyDE
  ([043](043-persona-search-embeds-the-wrong-shape.md)) is the natural query-translation
  step for a corpus whose documents do not read like questions.
- **Re-scoped again, 2026-08-04**, to this product's own behaviour. The reasoning is in
  *Why it is needed* and *What this corpus is not*.
- **The argument that died with it**, recorded so nobody rebuilds it: the corpus was going
  to hold Gligorić et al. 2023 (24,333 Upworthy pairs; second-person pronouns β +0.051,
  hypothesis rejected) beside our own 015 run (panel preferred *"you"* at 0.82 / 0.90 /
  0.94), so the analyst could surface the contradiction with both sources cited. It reads
  well and it is the wrong feature — see *What this corpus is not*. The figures stay
  where they belong, in `docs/lessons-so-far.md` and `docs/research/task-framing.md`.
- **The LangChain question, still open** and the implementer's call: a plain SQL retrieval
  function matching `nearest_panelists`, or `VectorStoreRetriever` over `PGVector`, which
  needs `langchain-postgres` (**MISSING**) and would be the first retrieval here not
  written as SQL. The retriever buys loader and splitter plumbing, which is a real
  consideration given heading-aware chunking is a decision above. **Write the choice
  down** — *"why not the framework's retriever?"* is a fair thing to be asked twice.

## Done when

A reader who cannot open the repo can ask *"what does high openness mean about this
panelist?"* or *"B is ahead — why is this undecided?"* and get an answer from **retrieved
passages with their sources shown**, not the model's textbook gloss. Which requires all of:

- a chunk table separate from `personas`, populated by a drop-and-reseed, with
  heading-aware splitting
- a retrieval function returning chunks **with citations**, exposed to the analyst
- the two-kinds rule rewritten so a question about a trait level or a credible interval
  routes to retrieval, **without opening the loophole** the 08-03 guard names — a question
  about this run's panel still goes to a tool
- every seeded figure carrying its conditions, so no document quotes an unconditional
  share for a quota-drawn panel or a resolution 020 already corrected away
- a handful of question → expected-source pairs; a full faithfulness harness is not needed
  to ship
- votes still ungrounded, so every number 014 and 015 measured stays comparable
