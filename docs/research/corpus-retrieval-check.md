# Does the explanation corpus actually serve a reader?

**Run 2026-08-26.** 15 chunks, 14 question–section pairs, 56 paid calls, well under
a cent. Harness: `backend/experiments/corpus_check.py`. Ticket: 018/#124.

## What was measured, and why in two stages

018 is explicit that retrieval metrics are not the bar: *"they prove the right
document was found, not that the reader was served."* So the harness has two stages
and only the second decides.

**Retrieval** — does the section that should answer a question come back?
**Judged** — a model answers from the retrieved passages and nothing else, and a
second model grades faithfulness and plainness separately.

The judged stage answers from passages directly rather than through the analyst
agent, so a failure says which half broke: this ticket owns whether a passage can
serve a reader, and 012 owns tool-routing.

Pairs were written before the run and phrased as a reader would type them — some
with the jargon off the report, some entirely without.

## The bug the first run found

**5 of 14 questions retrieved nothing at all**, including this corpus's own headline
question, *"B is ahead — why does it say undecided?"*

The cause was one function call. `websearch_to_tsquery` **ANDs** its terms, which is
right for a search box and wrong for a sentence:

```
websearch_to_tsquery('english', 'B is ahead — why does it say undecided?')
  -> 'b' & 'ahead' & 'say' & 'undecid'
```

No passage contains all four, so the keyword half matched nothing — and because a
passage must be lexically matched to be returned at all, nothing was returned.
`plainto_tsquery` would have behaved identically.

With the query's lexemes ORed instead, the same 14 pairs scored **12/14, top-1 on
10**.

The lesson is not "AND was the wrong default". It is that **a gate and its query
have to be designed together**: the lexical gate is what stops a vector search
returning its nearest neighbour to a question the corpus cannot answer, and it was
sound. Pairing it with an AND query inverted its meaning from *"must share a word"*
to *"must share every word"*, and nothing in the unit tests could see the difference
— they used a crude fake embedder and short queries where every term did match.

## What the two remaining failures were

Both were **mis-declared expectations, not retrieval failures**, and they are
recorded here rather than quietly re-labelled.

| question | declared | actually returned |
|---|---|---|
| what is the click-through rate for this headline | *(nothing)* | What the panel is actually measuring; Every panelist is invented |
| how do I write a better headline | *(nothing)* | What this panel cannot tell you |

The assumption was that a question outside the product's scope should retrieve
nothing. It was wrong: the corpus deliberately answers both, by explaining what the
panel measures and what it cannot show. The pairs now name those sections, and the
**12/14 figure above is against the original declarations** — these two were among
its failures.

The genuinely out-of-scope case is still covered by a unit test: *"how do I bake
sourdough"* shares no word with any passage and returns nothing.

## The judged stage: 14/14 faithful, 14/14 plain

Every answer said only what its passages supported, and every answer was one a
non-expert could use. Two read directly rather than taken on the judge's word:

> **B is ahead — why does it say undecided?**
> "B is ahead" means B had the larger raw share of panelists' votes. It is still
> **undecided** because the interval around that lead overlaps the tie zone. With
> this panel, a world where A and B are effectively equivalent has not been ruled
> out. Only when the entire interval lies outside the tie zone is the result called
> **decisive**.

> **what is the click-through rate for this headline**
> This panel does not provide a click-through rate. It reports the share of
> synthetic panelists who preferred one headline over the other, which is useful for
> comparing the headlines but does not predict real-world clicks.

The second is the one worth noticing. It is a question the model could have answered
with a plausible invented number, and instead it declined *using the retrieved
passage*. That is the corpus doing the job it exists for.

## Honest limits

- **14 pairs is a handful, and they are mine.** They were written by the same author
  as the corpus, which is the failure mode 094's guard run was caught by: a probe set
  built from the same imagination as the thing under test cannot find what that
  imagination missed. A reader's real questions will not look exactly like these.
- **One judge, one pass.** No agreement measured between judges, and no second
  sample. 14/14 on a set this size is consistent with a real pass rate well under 1.
- **The dense half is never tested alone.** Because membership is gated lexically,
  these numbers say nothing about how good the embeddings are — only that the
  ordering they produce is not harmful. A question sharing no word with any passage
  still returns nothing by construction.
- **Nothing here tests the analyst's routing.** Whether a live conversation actually
  reaches `explain_the_report` instead of answering from memory is 012's surface and
  is untested.
