---
title: "Task-framing sensitivity: does the verdict depend on how we ask the question?"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: closed
---

Resolved 2026-07-27 — [write-up](../research/task-framing.md).

## Goal

Find out whether the panel's verdict is stable across task framings, and pick the
one v1 ships with. Deliverable: a framing parameter on the vote prompt, and a
write-up beside
[`docs/research/manipulation-check.md`](../research/manipulation-check.md).

## Why

`app/llm.py:build_vote_messages` currently asks one specific question:

> "Which do you prefer? Pick option_1 or option_2, and give a one-line reason based
> on the content — not its position."

That is **abstract preference**. It could as easily ask about click intent ("which
would you be more likely to click?") or attention ("which would make you stop
scrolling?"), and nothing in the repo records why preference was chosen.

Two reasons this is worth an experiment rather than a taste call:

- **If the verdict flips with the wording, the headline number depends on an
  arbitrary choice** — and [011](011-build-report-ui.md) is about to render that
  number as a business decision. Better to know first.
- **The framing fixes what the number may be called.** Per the
  [009](009-build-bayesian-layer.md) amendment, ask preference → report a preference
  share; ask click intent → report a click-intent share. What we may never do is ask
  one and report the other. So the framing is not cosmetic; it is the definition of
  the reported quantity.

There is a real argument for the click framing — if CTR is the thing eventually to
be predicted, click intent is nearer that construct than abstract preference, and
intention measures generally track behaviour better than attitude measures. And a
real caution against assuming it helps: asking a model to imagine clicking is still
**self-report**, which is exactly the gap Han et al. 2025 documented (persona
injection moved self-reported agreeableness β=3.95, p<.001, and sycophancy behaviour
β=0.03, p=.67). A click framing may sound more predictive without being so.

## Design

Reuse [014](014-targeting-manipulation-check.md)'s harness. It varies the *persona*
half of the prompt; this varies the **task** half, holding personas and headline
pairs fixed.

**Change exactly one sentence.** The positional instruction and the
content-based-reason instruction stay word-for-word identical across arms, so the
only thing moving is the question itself. Otherwise this ablates framing and
instruction-following together — the same mistake
[006j](006j-persona-summary-embedding.md) D1b's three-vs-five arm had to avoid by
collapsing levels rather than rewording.

Three framings, agreed 2026-07-26 — the question sentence only, everything else held:

| id | question |
|---|---|
| `preference` | *Which do you prefer?* — what production ships today |
| `click` | *Which would you be more likely to click?* |
| `attention` | *Which one catches your eye?* |

`attention` deliberately avoids *"which would make you stop scrolling?"*, which
presumes a feed context half the stimulus set does not establish. No `purchase`
framing: *"which would make you more likely to buy?"* is two inferential steps from a
headline, and the construct argument for `click` does not reach it. Like the headline
pairs, these wordings are authored — so a null reads two ways, and the write-up has to
say which: the verdict is framing-robust, or these three are too alike to separate.

The `preference` arm must be **the production question itself**, not a copy of it — a
test asserting they are equal is what stops the shipped wording and the experiment's
baseline drifting into a silent fourth framing.

Two outcomes, pointing different ways:

- **Stable across framings** → the choice is low-stakes, so pick on construct
  grounds (click intent, being nearer the eventual target) and record that the
  verdict is robust to it.
- **Unstable** → the reported number is framing-dependent. That is a caveat that has
  to reach the report, and choosing becomes a real decision with nothing to ground
  it until there is outcome data (the Upworthy study, out of scope on the map).

**Secondary outcome worth collecting for free — position bias per framing.** 014
measured 0.66 overall and found it concentrates in cells where content preference is
weak; where the model has a real preference, order stops mattering. So a framing that
produces *less* position bias is one where the model is engaging with the copy rather
than defaulting to arrangement. That is an independent, behavioural reason to prefer
one framing, and it needs no outcome data to read.

## Amended 2026-07-26 — the stimulus set, and why 014's pairs cannot answer this

014's six pairs are **semantically opposed propositions**, not rephrasings: *"Taste
the flavour nobody has tried yet"* against *"The classic recipe, unchanged since
1954"* are different offers, almost different products. That was the correct
instrument for 014 — a trait can only move a vote on a pair where the trait predicts
a direction, and same-meaning pairs would have forced the effect to zero by
construction.

**It is the wrong instrument here, in a way that biases the answer toward the
comfortable one.** Real A/B tests hold the meaning and change the wording — the
Upworthy archive, this project's own validation target, is one article with
competing headlines. That is the regime the product ships into and no 014 pair is in
it. And 014 measured that position bias concentrates where content preference is
weak: same-meaning rephrasings are the *maximal* weak-preference regime, so testing
framing only on opposed pairs measures framing sensitivity where it should be
smallest, then reports "framing doesn't matter" and ships
[011](011-build-report-ui.md) with no caveat.

### Pairs

One proposition worded two ways, differing on exactly one lever — the stimulus-level
form of this ticket's "change exactly one sentence" rule. Predicted winners come from
Gligorić et al. 2023, whose twelve hypotheses were pre-registered and tested on
24,333 real Upworthy pairs, so no direction here is authored.

| id | lever | predicted | grounding |
|---|---|---|---|
| `pronoun_person` | 1st singular vs. plural | singular | β +0.241 vs. −0.149 |
| `person_number` | 3rd singular vs. plural | singular | β +0.216 vs. +0.094 |
| `article` | indefinite vs. definite | indefinite | β +0.125 vs. +0.033 n.s. |
| `second_person` | "you" present vs. absent | **no difference** | β +0.051, rejected |
| `control` | *(from 014)* | obvious option | comprehension |
| `openness` | *(from 014)* | trait-conditional | discrimination |

- `pronoun_person` — *I cut my grocery bill in half in one month* / *We cut our
  grocery bill in half in one month*
- `person_number` — *She rebuilt her savings in a year* / *They rebuilt their savings
  in a year*
- `article` — *A simple change that lowers heating costs* / *The simple change that
  lowers heating costs*
- `second_person` — *Three ways you can lower a heating bill* / *Three ways to lower
  a heating bill*

**`second_person` is a published negative control**, and the most valuable pair here.
Gligorić found second-person pronouns do *not* move real clicks. A panel that splits
strongly on it is manufacturing a preference where humans have none — a false-positive
detector with a citation behind it, which is stronger than anything 014 had.

**`openness` stays because a flat result is otherwise ambiguous** — framings agree, or
there was no signal to disagree about. It carries 014's steepest measured gradient, so
it proves the panel could discriminate under these framings at all.

Rejected levers, and why: **negative emotion** (β +0.180, confirmed) cannot be swapped
without changing the proposition — *"errors that waste thousands"* against *"fixes that
save thousands"* is loss-vs-gain framing, a different and here-unsourced lever, and
would have reintroduced the exact problem this amendment fixes. **Concreteness** (Aubin
Le Quéré & Matias 2025) is curvilinear — it helps below a test-average of 2.58 and hurts
above 3.06 — so an isolated pair has no predicted direction. **Length** (β +0.074) adds
information, so it is not meaning-preserving.

### Schema

`HeadlinePair.trait: str | None` currently means "trait-loaded, or `None` for the
control". Four pairs now have no trait, so `None` no longer identifies anything —
and `CONTROL_PAIR = next(p.id for p in PAIRS if p.trait is None)` would silently
resolve to whichever untraited pair is listed first. The comprehension check and the
noise-floor exclusion would then both read off the wrong stimulus, with nothing
raising. **This must be fixed in the same change as the pairs, not after.**

So the pair gains two fields:

- **`grounding: str | None`** — the published source for the predicted direction,
  `None` where the pair is authored. Making the unsourced ones visible in the data is
  the point; today it is only knowable from a docstring.
- **`role`** — `trait` | `published` | `published_null` | `comprehension`. One
  discriminant instead of three flags that can contradict each other, and it makes
  `CONTROL_PAIR` unambiguous by construction.

Convention to hold: **`predicted_high` is always the variant carrying the lever**, so
a `published_null` pair predicts a share of 0.5 rather than leaving the assignment
arbitrary. Analysis reads the same way for every population-level pair — share
choosing `predicted_high`, per framing, against 0.5.

One knock-on in `analysis.py`: `_loaded()` excludes `CONTROL_PAIR` from the noise
floor and flip rates because it is authored so that no persona disputes it. The
`published_null` pair is **not** in that category — the model has a genuine choice
there — so only the comprehension pair stays excluded.

### Caveats for the write-up

- **Gligorić's β's are within-experiment associations over naturally-occurring
  headlines, not controlled minimal-pair manipulations.** The pair structure controls
  for the article, but features co-vary. Building a minimal pair and expecting the
  same direction is our extrapolation: only the *directions* transfer, never the
  magnitudes, and β = 0.241 is not "24% more clicks".
- Upworthy is 2013–2015 social-news content; these pairs are product marketing.
  Domain transfer is an assumption.
- Six pairs cannot validate the panel against real clicks. Per-pair agreement at n=6
  is noise. Effect-level replication — many personas per lever, checked against the
  paper's direction — is the real version and is **a separate ticket**, not this one.

## Scope

**In:** three framings, the six pairs above, the existing sweep personas, both
presentation orders, position bias per framing, and the write-up.
3 framings × 25 sweep personas × 6 pairs × 2 replicates × 2 orders = **1,800 votes,
~17 minutes** at 014's measured 0.551 s/vote.

Both selections have to be passed. `--arms` defaults to all three, and `--pairs`
defaults to all ten — the other four 014 pairs stay in the registry so that run's
collected votes still analyse, but re-running them here would cost 3,000 votes to
answer nothing 014 has not:

```
uv run python -m experiments.manipulation_check --replicates 2 --arms traits_5 \
  --pairs pronoun_person,person_number,article,second_person,control,openness \
  --out experiments/out/framing.jsonl
uv run python -m experiments.analysis experiments/out/framing.jsonl
```

**Out:** whether any framing predicts real click-through. That is validation against
field outcomes and is out of scope on the map.

## Code this needs

The task text is hardcoded inside `build_vote_messages`, so the question sentence has
to become a parameter with the current wording as its default. Same shape as the
`render_demographics_prompt` extraction 014 needed — production keeps its behaviour,
and the experiment gets a seam rather than a second copy of the prompt that can drift.

Bind it at construction (`OpenRouterPanelLLM.__init__`), not per call: one test asks
one question of everybody, so the question is panel configuration, not vote data.
That leaves the `PanelLLM` protocol, `vote()`, `collect_panel_votes` and `main.py`
untouched — and avoids repeating 014's reverted `render` parameter, an experiment-only
knob on the production per-call path. The harness then holds one client per framing.

Splitting the prompt constant in two — the question, and the invariant
`Pick option_1 or option_2…` instruction — is what makes "change exactly one sentence"
structural rather than remembered: the positional instruction is not in the parameter,
so an arm cannot reword it by accident.

Then framing becomes a sweep dimension alongside `arm` (`Cell`, `VoteRow`,
`plan_cells`, `--framings`), and `VoteRow.framing` defaults to the shipped framing so
014's 5,400 collected rows still parse — backfilling `preference` records what those
votes actually used.

**The one that can invalidate the run:** `analysis.py`'s
`_CELL = ("arm", "trait", "persona_id", "pair_id", "order")` defines "the same prompt,
run twice". Without `framing` in it, replicates of *different framings* group as
identical re-runs, the noise floor absorbs the whole framing effect, every flip rate
lands at the floor, and the run concludes "framings are interchangeable" regardless of
what the model did. `gradient` and `position_bias` need the same parameter. Pin it with
a test first: two framings disagreeing on every matched vote must give a floor of 0.00,
not 1.00.

## Consumers of the answer

- **[009](009-build-bayesian-layer.md)** — what the reported quantity is called.
- **[011](011-build-report-ui.md)** — whether the report has to carry a
  framing-dependence caveat.
- **[002](002-decide-vote-schema.md)** — the question is part of the vote contract;
  it currently specifies a content-based reason and positional voting but says
  nothing about the question itself.
