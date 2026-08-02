---
title: "The persona search embeds a question against a corpus of profiles"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The asymmetry (2026-08-02, tracing what `search_personas` actually embeds)

Every vector in `personas.summary_embedding` was produced from one fixed sentence shape
(`panel.py:124`), and the real output is long, third-person and demographic:

```
A 24-year-old male living in the United States, who finished secondary school but didn't
go to university, with an income in the lower income range for that country. By
temperament: firmly set in familiar ways, with little appetite for anything untried;
organized and self-disciplined, careful to think things through; highly gregarious,
energised by crowds and rarely quiet for long; highly guarded and blunt, treating most
claims as suspect; subject to the usual ups and downs but mostly even-keeled.
```

`search_personas` embeds whatever string the model passes as `query` and ranks that
against those vectors. Today the docstring asks only for *"a plain-language
description"* — so a query like `"older, cautious"` or, worse, a near-passthrough of the
customer's question, gets embedded and compared against the paragraph above.

**Cosine distance finds *similar*, not *related*.** A question and the profile that answers
it are related; they are not similar texts. Register, length, person and vocabulary are all
encoded, so a short interrogative and a 60-word third-person description sit apart even when
they concern the same person. Two smaller versions of the same problem:

- The retrieval-relevant span is a fraction of the text. In *"were the older ones more into
  B?"* only *"older"* selects anyone; `"B"` appears in no summary and is meaningless outside
  this app, and one embedding is one average, so the rest drags the vector off target.
- It degrades with length. A multi-part question becomes one averaged vector that matches
  every part of itself weakly.

## The fix, and why it costs nothing here

**HyDE** — Hypothetical Document Embeddings (Gao et al. 2022): don't embed the question,
have a model write the *document* that would answer it, and embed that. The invented
document may be factually wrong; it is a probe, not a claim. What it buys is a
**document-to-document** comparison, where cosine is the right instrument.

Textbook HyDE costs an extra model call per search. **Here it costs none**, because the
agent is already choosing the tool and writing its argument — so "write a hypothetical
profile" is a change to the tool's description, not a new step in the graph. That is the
whole reason this ticket is cheap enough to be worth filing.

The docstring already gestures at it (*"The query describes people, not SQL"*), so this is
finishing a move that was started, not introducing a new idea.

### Proposed wording, ready to apply

```
Individual panelists of THIS test whose profiles best match a plain-language
description, nearest first — for characterizing or quoting particular people. For
the panel's overall make-up call analyze_results instead: this returns a handful of
profiles, never a distribution.

Write the query as the profile of the person sought, phrased the way the profiles
themselves are: "A 61-year-old male living in Germany, who finished secondary school
but didn't go to university, with an income in the lower income range for that
country. By temperament: firmly set in familiar ways; highly guarded and blunt."
Invent the specifics freely — the text is a probe, not a claim about anyone. A
question ("who liked B?") matches other questions rather than profiles, so it
retrieves worse than an invented profile of the same person would.
```

**Every phrase in that example is verbatim from the live template**, not plausible-looking
prose: `"finished secondary school but didn't go to university"` is
`_EDUCATION_PHRASE[SECONDARY]`, `"the lower income range"` comes from `_income_band`, and
both temperament clauses are real `_TRAIT_PHRASES` entries. An example that merely *looks*
like a summary would aim the probe at a region of the space the pool does not occupy, which
is worse than the vaguer instruction it replaces.

## The coupling this creates, and how to pin it

The example lives in `analyst.py` and the text it must match is generated in `panel.py`.
Nothing connects them, and `panel.py:82` already warns that reshuffling that wording is *"a
re-embedding bill rather than a cosmetic change"* — so a reword there would silently leave
the probe aimed at a shape the pool no longer has.

A test over the literals they share, asserted **in both directions**, closes it:

```python
for shared in ("-year-old", "living in", "income range for that country",
               "By temperament:"):
    assert shared in persona_summary(FIXED_PANEL[0])
    assert shared in tools["search_personas"].description
```

## What no test can check, and it is the fourth instance today

`test_analyst.py` and `test_main.py` drive this tool with
`tool_call_message(name="search_personas", args={"query": "thrifty"})` — the query is
**hardcoded by the test**, so the docstring cannot influence anything the suite observes.
Whether the model actually writes profile-shaped queries takes a live call.

That is [039](039-culture-tag-cannot-say-neither.md)'s pattern again — *a test that
constructs an input the model does not emit* — and it is worth stating here because it
determines what "done" can mean: the suite can pin the wording and the coupling, and only a
live turn can show the behaviour.

## Cost, stated rather than assumed

The description is sent in the tool schema on **every analyst turn**, so this trades tokens
per turn for retrieval quality. The added text is roughly a hundred tokens; **that figure is
counted, not measured against a bill**, and no per-turn analyst cost is recorded anywhere in
`docs/research/`. If it matters, it is measurable the same way [033](033-a-run-records-its-own-time.md)
made wall time measurable, and it should be measured rather than argued about.

## Three alternatives, deferred not rejected

All three are real improvements and all three cost more than this one:

| option | cost | why not now |
|---|---|---|
| **Rerank** — over-fetch `LIMIT 50`, score against the query, keep 5 | one model call per search | the strongest fix; wants its own ticket, and wants [041](041-which-traits-moved-the-vote.md) settled first |
| **Relevance grader** (Self-RAG / CRAG) — grade what came back, re-query if poor | a call per retrieval, plus a graph loop | answers *"the model trusts its tools completely"*, which is a design change not a wording change |
| **Query rewriting as a separate step** | one call, and it duplicates what the agent already does | strictly worse than putting the instruction in the description |

## Sequencing: after the sprint review, and possibly never

**Held until after the graded review (decided 2026-08-02).** It changes a live prompt, and
the only way to see the effect is a paid live turn — not something to do while the demo path
is the priority.

**And it may be superseded.** [041](041-which-traits-moved-the-vote.md) defers the
keep-or-remove call on `search_personas` until its own cross-tab ships, on the grounds that
top-5 by cosine says nothing about a 200-panel and is variant-blind. If 041 lands first and
the tool goes, **close this ticket rather than implementing it** — a better-aimed probe into
a tool nobody should be using is wasted work. It is filed now because the analysis is done
and cheap to lose, not because it is urgent.

## Done when

The tool's description asks for a profile rather than a description, its example is verbatim
from `persona_summary`'s live wording, a test pins those two together in both directions —
and one live turn is on record showing the query the model actually writes, since that is the
only evidence the change did anything.
