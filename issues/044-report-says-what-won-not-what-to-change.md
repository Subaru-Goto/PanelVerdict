---
title: "The report says which headline won and why, never what to change"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The gap (raised 2026-08-03)

A finished report carries four things: the verdict and its share, *"What the panel said"*
(the analyst's opening reading of `read_reasons`), the panel's make-up, and the notices. A
customer reads all of it and still has exactly one action available: **ship B**.

Nothing says *what to change*. And the commercial value was never in choosing between two
headlines somebody already wrote — it is in writing a better third one.

| question | answered today |
|---|---|
| which won? | yes — `verdict`, `tally` |
| why? | yes — `read_reasons` via the opening turn |
| who preferred it? | no — [041](041-which-traits-moved-the-vote.md) |
| **what should I change?** | **no — this ticket** |

## Where it goes: three options, and the cheap one is also the best

| option | cost | why not |
|---|---|---|
| a field on `EvaluateResponse`, computed in the pipeline | a model call on **every** test | paid whether or not anyone reads it, and `/evaluate` is the path with the spend caps and the 402 handling — adding a generative step there widens the most expensive endpoint |
| a fourth analyst tool | a tool call per use | breaks `build_tools`' stated invariant: *"Every one of them reads. None of them spends, and none of them writes."* All three existing tools return recomputed figures or stored words. A tool that **generates** is a different kind of thing wearing the same shape |
| **a second opening request from the report** | one model turn per rendered report | **recommended** |

The third option needs no new endpoint, no new tool and no schema change — it reuses the
mechanism `OPENING_REQUEST` already established (`use-analyst.ts:21`), which is the
report asking a question on the reader's behalf and rendering the answer as a card.

**And the reasons are already paid for.** `ChatRequest` records that *"the checkpointed
transcript keeps ToolMessages, so a follow-up is answered from context instead of re-buying
the tool calls a text-only replay would drop."* Turn 1 already pulled every vote reason into
the thread; a suggestion turn reads them from the transcript. So the marginal cost is one
model call, not a second retrieval.

## The constraint that separates a finding from a copywriting toy

**Every suggestion must be traceable to something a panelist actually said.**

*"Use a number in the headline"* is generic copy advice; the product did not need 200 votes to
produce it, and a customer can get it free anywhere. *"Eleven panelists who chose B said the
price was the thing that landed, and A never mentions it"* is a finding — it exists only
because this test ran.

That also settles the grounding question: suggestions come from **patterns across reasons**,
not one cherry-picked reason. With ~200 reasons in the transcript, a single quotable sentence
is available for almost any claim, which makes single-reason grounding indistinguishable from
invention.

## The system prompt has no category for this, and that is the real work

`analyst.py:78` splits every question in two:

> *"Anything about THIS test … comes from a tool every time: never from memory, never
> estimated, never inferred … Anything general — what a credible interval means, **why a
> headline might land**, what this method can and cannot show — you answer yourself,
> directly."*

A suggestion is **neither**. It is copywriting judgement *applied to* tool output — general
knowledge and test facts in one sentence, which is the one combination the rules do not
describe. Note the bolded clause: *"why a headline might land"* is already licensed as
general knowledge, so the raw capability is present and only the grounding rule is missing.

**The hazard is that a third clause becomes a loophole.** The two-kinds rule is what stops
the analyst inventing figures, and it works because it admits no middle. A clause reading
"when suggesting, combine the panel's reasons with what you know about copy" is exactly the
shape through which *"the panel skewed young"* gets answered from memory. Whatever wording
ships has to license generation about **copy** while leaving the ban on generation about
**this test** intact — and that is a prompt-engineering problem, not a plumbing one.

## Honesty: this is the least verifiable thing the product would emit

Everything in the report today is either computed (`verdict.py`), counted (`analyze_results`)
or quoted (`read_reasons`). A suggestion is none of the three. It cannot be checked against
the test that produced it, which sits awkwardly beside two standing commitments:

- [020](020-probability-not-label.md) replaced a label with a probability because a bucket
  claimed more than the data supported.
- [038](038-education-reading-is-never-disclosed.md) shipped `*_source_phrase` so the
  model's reading is *disclosed rather than legislated* — *"no reading is legislated
  anywhere in this project."*

So a suggestion must be presented as a **hypothesis, not a finding**, and the wording is
part of the deliverable rather than a polish pass. *"Worth testing"* is honest; *"you should"*
is not.

### The move that redeems it: the loop already exists

The report has **Test again** (`analyst.py:96`). So a suggestion is not an unfalsifiable
opinion — it is a hypothesis the product can immediately test, using the same machinery, for
~$0.145. *Suggest → test → verdict* is a real loop, and it turns the weakest output in the
system into the input of its strongest one.

Worth stating in the ticket because it also fixes the framing: the suggestion is not the
answer. It is the next question.

## Security: this reopens the path 012 deliberately closed

`build_tools` records why the analyst lost `run_panel_test`:

> *"the only path by which a model could spend money — reached, in principle, by a crafted
> headline becoming a vote reason that `read_reasons` hands back."*

And `vote_reasons` names the surface directly: *"the first thing the analyst reads that
another model wrote — every other tool serves recomputed figures or code-composed prose."*

**A suggestion generator is fed exactly that text.** So the injection path is unchanged in
shape and **worse in payoff**: instructions smuggled through a vote reason no longer merely
try to trigger a tool, they try to become *advice the customer acts on*. Two requirements
follow, and neither is optional:

- **No new tool, and no ability to start a test.** The suggestion turn must stay inside the
  existing read-only tool set. If it ever gains the ability to act on its own suggestion,
  012's deleted path is back with money attached.
- **The screening that guards `/evaluate` does not guard this.** Screening runs on the
  customer's input; a vote reason is model output generated *after* it. Whether that needs
  its own check is an open question this ticket should not answer by silence.

## Cost, and what is not known

One extra model turn per rendered report, on the analyst model. **No per-turn analyst cost is
recorded anywhere in `docs/research/`** — the same gap [043](043-persona-search-embeds-the-wrong-shape.md)
names — so the honest statement is that the marginal cost is one call of unmeasured size, and
[033](033-a-run-records-its-own-time.md) is the precedent for measuring rather than arguing.

Also unknown, and worth measuring in the same pass: whether a second card is what a reader
wants, or whether suggestions belong inside *"What the panel said"* as its closing sentences.
Two cards is more code; one card risks burying the part the customer came for.

## Testability, stated up front

Same ceiling as the rest of the analyst. A test can pin that the turn fires, that it renders,
that a failure degrades like the summary card's does, and that the tool set stayed read-only.
**No test can check that a suggestion is any good** — that needs a live turn and a human
reading it. Anyone expecting the suite to defend the feature's quality will be disappointed
for the same reason 039 named three times.

## Done when

A finished report tells the customer something to try, every part of it traceable to what
panelists said rather than to general copy wisdom, worded as a hypothesis rather than a
recommendation — and the reader can send it straight back through **Test again** to find out
whether it was right.
