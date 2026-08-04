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

- **the Big Five** — what a trait is and what a level means
- **the Bayesian decision** — what the band and the interval are, and why they are there

**The corpus holds concepts and method. It holds no figures.** Every number a reader needs
is already in the payload or comes from a tool — see
[What never goes in](#what-never-goes-in-the-corpus). That single rule is what keeps a
retrieved answer from ever contradicting the report it explains.

Rewritten 2026-08-04. What changed and why is in [History](#history) — including the
corpus this ticket used to describe, and the argument that killed it.

## Why it is needed: the reader cannot read the source, and the model answers anyway

A customer has **no access to the code**. So when they ask what a trait level means, the
analyst answers from the model's own weights — and the model's most probable answers are
each wrong *about this product*:

| the likely answer | what the corpus says instead | grounded in |
|---|---|---|
| these are people's questionnaire responses | every panelist is **synthetic** — traits were drawn from population statistics, never collected from anyone | `VoterSummary`: *"Every voter is synthetic — a sampled persona, not a person"* |
| openness tracks education, culture, nationality | the draw is conditioned on **age and gender only**, so a trait level carries no claim about country | `bigfive.py:17` — *"country does not condition the Big Five μ"* |
| a textbook definition of openness | what the level *means about this panelist*: appetite for novelty against preference for the familiar | `panel.py`'s level descriptions, BFI-2-style (`persona-seed-data.md`) |
| a lean toward B is a result | a lean inside the band is **not** a result, and *"credibly too small to matter"* is a positive finding rather than a null one | `verdict.py:279-284` — *"the third is the point of the method"* |

These are not obscure failure modes — they are the *default* completions. And the reader
cannot catch any of them. That is hallucination in the form that costs something: not
fabricated trivia, but a confident mismatch with what the system did, delivered to
somebody with no way to check it.

**Note what is deliberately absent: percentiles.** *"Is `HIGH` the top fifth?"* has a
figure for an answer, and figures are not this corpus's job — the honest response is that
the report expresses a level, not a rank. Seeding the cutoffs would have been worse than
unhelpful: `bigfive.py:58` warns that the clean population shares describe the
*unconditional* normal and *"a demographically conditioned cell skews off those shares"*,
so a document quoting them flat for a quota-drawn panel would commit this ticket's own
defect **while citing a source**. The no-figures rule removes the possibility rather than
guarding against it.

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

The old version answered the fair objection *"that's just SQL"* by pointing at published
papers. That defence went with them, and the concepts-only rule sharpens the question
rather than settling it: **a model can already define a ROPE.** So the claim has to be made
honestly, in three parts.

- **The weakest part, stated first.** Some of this is material the model broadly knows.
  *"What is a credible interval?"* is not a fact it lacks. Pretending otherwise would
  repeat the previous version's overclaim.
- **What retrieval buys even so: the same answer every time, with a source.** An
  explanation from weights is unfalsifiable and varies turn to turn; a retrieved one is
  fixed and points at a document the reader could be shown. For a product whose entire job
  is explaining a number somebody paid for, a *consistent, checkable* explanation is the
  feature, not a nicety — and it is what the sources requirement in Scope is for.
- **And the stance is ours, not the textbook's.** A generic explanation of a ROPE will not
  say that *this* product treats `practical_tie` as a **positive finding** rather than a
  null result, or that it demands the whole interval clear the band rather than merely lean
  past it. `verdict.py:279-284` calls that third outcome *"the point of the method."* That
  is an editorial position, and a model has no way to guess it.

**The strongest part is composition.** *"B is ahead — why is this undecided?"* is answered
from three retrieved concepts — what the band is, why the interval must clear it entirely,
what a null result can show — joined to three values off the wire: `rope`,
`credible_interval`, `detectable_gap`. No single passage holds that answer, and no `WHERE`
clause reaches it. **That** is the similarity search earning its name, and it is the shape
worth demonstrating.

So the requirement is met by the *shape of the answer*, not by the corpus being exotic.
That division — retrieved concept, live number — is also exactly what keeps the two-kinds
rule intact.

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

Concepts and method, phrased for a reader who is neither a statistician nor a
psychometrician. No figures — see the rule below.

| subject | the question it answers | grounded in |
|---|---|---|
| what a trait is | what each of the five traits describes, and what a level says about a panelist | `panel.py` level descriptions, `docs/research/persona-seed-data.md` |
| how a panelist came to exist | traits drawn from population statistics, conditioned on age and gender; synthetic throughout, and what that limits | `bigfive.py`, `persona-seed-data.md`, Donnellan & Lucas cited |
| what a credible interval is | how it differs from a confidence interval, and why a range rather than one number | `verdict.py` `posterior` |
| what the band is and why | why a difference can be real yet too small to act on, and why the product takes a stance on that at all | `verdict.py` `rope_verdict` |
| why *"ahead"* is not *"decisive"* | why the whole interval must clear the band, not merely lean past it | `verdict.py:279-284` |
| what the three outcomes mean | `decisive`, `undecided`, `practical_tie` — and that the third is a **positive finding**, which *"not significant"* can never say | `verdict.py:279-284` |
| what a null result can and cannot show | why *"this panel could have detected a gap this wide and found none"* is readable where bare `undecided` is not | `verdict.py` `detectable_gap` |
| why it may stop early | that the run stops when the answer is already in, and that this is a cost decision with a stated confirmation rule | `docs/research/adaptive-stopping.md` |
| what the method cannot tell you | the panel is unvalidated on same-meaning copy — 015's negative control | `docs/research/task-framing.md`, README *Known limitations* |

### The rule: concepts and method, never figures

**If a statement contains a number that also exists in code or on the wire, it does not go
in the corpus.** The reasons compound:

- **The figure is already there.** `PanelVerdict` carries `rope`, `credible_interval`,
  `credible_mass` and `detectable_gap`, and `schemas.py:243` is explicit that *"`rope`
  travels with the verdict rather than being implied."* A retrieved copy would duplicate a
  fact the payload already supplies.
- **A duplicate can disagree.** Two homes for one number means the analyst can cite a
  document that contradicts the report on the same screen — with a citation attached,
  which is worse than no answer.
- **It respects the two-kinds rule instead of straining it.** Numbers stay tool facts;
  concepts become the retrieved third kind. That makes the new clause narrow by
  construction, which is what the 08-03 loophole guard was asking for.
- **`docs/research/` is not the corpus.** Those documents are dense with figures —
  `manipulation-check.md`'s measured effects, `adaptive-stopping.md`'s confirmation
  counts. They are the *grounding* a corpus document cites, not text to chunk wholesale.

**The worked example of why.** `detectable_gap` at *n* = 200 is ±13.9, and
[020](020-probability-not-label.md):113 records that **±14 was a rejected first pass** —
it expressed the gap as a raw vote share while every other number in the payload lives in
the posterior share. A corpus document quoting ±14 would authoritatively cite a figure this
repo had already corrected away. Under this rule no document quotes either: the concept
*"the smallest gap a panel this size could have called decisive"* is seeded, and the value
comes from the verdict.

### What never goes in the corpus

Already on the wire, so retrieving them would be duplication at best and contradiction at
worst:

- `verdict.rope`, `credible_interval`, `credible_mass`, `detectable_gap`
- `stop_reason`, `tally`, `counts`
- each voter's demographics and trait **levels** (`VoterSummary.traits`)

And out of scope by [What this corpus is not](#what-this-corpus-is-not-and-why): anything
about how real people respond to copy.

**The asymmetry worth noticing:** `VoterSummary` gives the reader `openness: HIGH` — a bare
enum label. The *value* is on the wire and the *meaning* is nowhere. That is the gap this
corpus fills, and it is exactly the shape of the division above.

## The bar: the analyst has to answer the topic *well*

**This ticket is judged on user value, not on plumbing.** A chunk table, a retrieval
function and a citation are all necessary and none of them is the goal. The goal is that
somebody who is not an analyst asks *"why is this undecided when B is ahead?"* and gets an
answer they can act on.

Two consequences that shape the work rather than decorate it.

**The documents are written for the reader, not transcribed from the code.** This settles
what was previously left open. `verdict.py`'s docstrings are excellent and are written for
engineers — *"for a skewed posterior the equal-tailed interval can include values less
plausible than ones it excludes"* is exactly right and is not an answer for a marketer.
Chunking them verbatim would hand engineer prose to a lay reader with a citation attached,
which reads as evasion. So each document is **newly written as reader-facing explanation**,
citing the code and the research rather than quoting them. Hand-written wins for a
user-value reason, not a maintenance one.

**A retrieved answer must be better than the model's own, or the corpus is overhead.** That
is the comparison to actually run, and it is uncomfortable on purpose: for *"what is a
credible interval?"* the weights may well win on fluency. The corpus has to earn its place
on the axes it can win — the same answer every time, a source the reader can check, and
this product's stance (`practical_tie` as a positive finding) which no generic explanation
contains.

## Decisions this ticket has to make

**Chunking.** Fixed-size with overlap is the default, but these are section-structured
markdown documents. Splitting on headings keeps an explanation with the caveat that
qualifies it — and a concept severed from its caveat is precisely the confident-but-wrong
answer this ticket exists to prevent. Prefer heading-aware, fall back to fixed windows
inside an over-long section.

**How answer quality gets measured.** Retrieval-hit metrics are not the bar above, so
question → expected-source pairs are necessary but not sufficient: they prove the right
document was found, not that the reader was served. This is where judge-based tooling
(RAGAS, DeepEval) finally earns its place, having been the wrong instrument for
[016](016-translation-accuracy-golden-set.md) and 017 — the output here is prose with no
single right answer, which is the case judges are for. Two things to check, and the second
is the one that matters:

- **faithfulness** — the answer says only what the retrieved passages support
- **whether a non-expert is actually served** — answered in plain language, and not
  contradicting the numbers on screen

A handful of pairs plus a small judged set is enough to ship. A full harness is not
required, but *"the right chunk came back"* alone is not evidence this ticket succeeded.

## What the concepts-only rule already removes

Worth recording, because an earlier draft of this ticket treated it as the design's main
hazard: a corpus derived from source files **goes stale silently**, and a document
confidently describing behaviour the code no longer has is *worse* than answering from
weights, because it arrives with a citation.

That hazard is now **structural rather than managed**. Documents hold no figures and quote
no constants, so there is nothing in the corpus for a change to `_ROPE` or
`_TRAIT_PHRASES` to falsify. Drop-and-reseed stays the convention because the corpus is a
cache of committed documents, but it is no longer load-bearing for correctness.

**What can still drift is a stance, not a number.** If the product stopped treating
`practical_tie` as a positive finding, a document saying it does would be wrong — and no
reseed catches that, because the document is not derived from the code. Narrow, slow-moving,
and the residue worth stating rather than a reason to hold figures.

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
- **Narrowed the same day to concepts and method, no figures.** The first pass at the
  re-scope would have seeded the ROPE bounds, the trait cutoffs and `detectable_gap` — all
  of which `PanelVerdict` already puts on the wire. Duplicating them bought nothing and
  risked a cited document disagreeing with the report beside it. Seeding *"what the band is
  and why a product takes a stance on it"* and reading the bounds off the verdict is
  strictly better, and it retires the staleness hazard the earlier draft called this
  design's main risk.
- **And the bar moved with it**, same day: the measure is whether the analyst answers the
  topic *well* for a non-expert, not whether the pipeline retrieves. That settled the
  hand-written-versus-generated question — engineer docstrings, chunked verbatim, are not
  an answer for a marketer — and moved judged answer quality from a v1 nicety to the
  evidence this ticket worked.
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

**A non-expert asks *"B is ahead — why is this undecided?"* and gets an answer they can act
on** — the concept from retrieved passages with their sources shown, the numbers from the
verdict, in language that needs no statistics. That is the test; everything below is what it
takes to pass it.

- a chunk table separate from `personas`, populated by a drop-and-reseed, with
  heading-aware splitting
- documents **written as reader-facing explanation**, not chunked docstrings, each citing
  the code or research it rests on
- **no figure in any document that also exists in code or on the wire** — the analyst
  composes retrieved concept with live value
- a retrieval function returning chunks **with citations**, exposed to the analyst
- the two-kinds rule rewritten so a question about a trait level or a credible interval
  routes to retrieval, **without opening the loophole** the 08-03 guard names — a question
  about this run's panel still goes to a tool
- question → expected-source pairs, **plus a judged check that the answers are faithful and
  plain** — retrieval hits alone are not evidence this succeeded
- votes still ungrounded, so every number 014 and 015 measured stays comparable
