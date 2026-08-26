# Does the explanation corpus actually serve a reader?

**Run 2026-08-26**, three stages, ~120 paid calls, well under a cent. Harness:
`backend/experiments/corpus_check.py`. Ticket: 018/#124.

Headline: **the first version of this corpus taught a verdict rule the product had
abandoned, and the first version of this harness graded it faithful.** Both are
fixed; what follows is what the corrected run measures, and what it still cannot
see.

## The bug that mattered most

The corpus defined the report's answers as **Decisive / Undecided / Practical tie**,
decided by the credible interval clearing the tie zone — which is `rope_verdict`,
whose own docstring opens *"Not what a report carries."*

The reader never sees any of that. `frontend/app/components/report.tsx` derives the
label from probability mass against a bar: **Panel leans clearly**, **Practical
tie**, **No call at this credibility**. The words "decisive" and "undecided" appear
nowhere in the UI.

So a reader would have asked why their result was undecided — using a word the
product does not use — and been handed a confidently-cited explanation of a rule it
does not apply. That is precisely the failure this corpus was built to prevent, with
a citation attached to make it worse.

**It was found by code review, not by this harness**, and the reason is the second
bug: the judged stage passed `chat` as both the answerer and the judge. One model
instance grading its own output shares every blind spot with the thing under test,
and it duly scored the wrong-rule answer faithful. The judge now runs on
`settings.judge_model`, a separate client.

## Stage 1 — retrieval: 12/16, top-1 on 10

Sixteen question–section pairs, written before the run and phrased as a reader would
type them. Two ask the same thing in the two vocabularies that exist — *"why does it
say no call"* (what the screen shows) and *"why is this undecided"* (what people
say) — because both have to work.

The four misses, classified rather than averaged:

| question | wanted | returned | verdict |
|---|---|---|---|
| B is ahead — why does it say no call? | Why being ahead is not… | What the report can answer… | **defensible** — the returned section defines "no call" directly |
| what is the click-through rate…? | What the panel is measuring | Every panelist is invented | **defensible** — both say why there is no CTR |
| is a tie a failed test | What the report can answer… | What this panel cannot tell you | **a real miss** — "failed"/"test" pulled it to the limits section |
| how do I write a better headline | What this panel cannot tell you | *nothing* | **the expectation was wrong** — the corpus cannot tell you how to write copy, so declining is right |

Single-section pairs are a blunt instrument when a corpus can legitimately answer
from two places. That is why the ticket calls them necessary and not sufficient, and
why the number is reported with its misses classified rather than as a score.

## Stage 2 — judged: 16/16 faithful, 16/16 plain

A model answers from the retrieved passages and nothing else; a **separate** model
on `judge_model` grades faithfulness and plainness independently. Declining is scored
as success in both: an answer saying the material does not cover the question is
faithful and plain, and it is what the empty-retrieval path exists to produce.

## Stage 3 — routing: 7/7

Retrieval and answer quality are worth nothing if the analyst never reaches for the
corpus. Measured on live turns, recording which tools actually fired.

**The first run was 6/7.** *"Are the panelists real people?"* called **no tool at
all** — the model answered from its own knowledge, which is the exact behaviour this
ticket exists to end. The prompt now says to call the tool *even when you think you
know the answer*, because believing you already know is the case it exists for. 7/7
after.

The loophole holds in the other direction: questions about this run's numbers still
go to `analyze_results`, never to the corpus, which carries no figures to contradict
a verdict with.

## The lexical gate, and what it cost to get right

A passage must be lexically matched to be returned; the embedding orders, it does not
admit. Without that, a vector search returns its nearest neighbour to any question at
all, and the analyst cites it.

The gate was implemented twice wrong before it was right, and both failures were
measured rather than reasoned about:

- **AND** (`websearch_to_tsquery`'s default) demanded every word of the question.
  *"B is ahead — why does it say undecided?"* became `'b' & 'ahead' & 'say' &
  'undecid'`. **5 of 14 questions retrieved nothing.**
- **OR** demanded any single word. **12 of 15 plainly out-of-scope questions came
  back confidently cited** — "who won the world cup" returned two passages about the
  tie zone.
- **Strict majority** — more of the question matched than did not — declines 9 of 10
  out-of-scope questions while answering 8 of 8 in-scope ones. Better on both sides
  at once, which is what distinguishes a rule from a tuned threshold.

Its honest ceiling: *"how much does this cost"* passes, because both content words
genuinely appear ("a **cost** decision", "how **much** someone plans"). A lexical
gate cannot tell a question about price from a passage that uses the word.

## Honest limits

- **Sixteen pairs, written by the corpus's own author.** The failure mode this
  project has been bitten by twice: a probe set built from the same imagination as
  the thing under test cannot find what that imagination missed. It did not find the
  verdict-rule bug; a reviewer reading `report.tsx` did.
- **One judge, one pass.** No inter-judge agreement, no second sample. 16/16 on a set
  this size is consistent with a real pass rate well under 1.
- **The dense half is never tested alone.** Membership is decided lexically, so these
  numbers say nothing about embedding quality — only that the ordering is not
  harmful.
- **Only text has been evaluated.** Image evaluation is planned as v2; nothing here
  measures it, and the corpus keeps its validity caveat explicitly scoped to written
  headlines rather than implying coverage it does not have.
- **Routing was measured on seven questions and one report.** A different verdict
  shape, or a longer conversation, is untested.
