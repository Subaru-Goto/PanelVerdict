---
title: "Task-framing sensitivity: does the verdict depend on how we ask the question?"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Goal

Find out whether the panel's verdict is stable across task framings, and pick the
one v1 ships with. Deliverable: a framing parameter on the vote prompt, and a
write-up beside
[`docs/research/manipulation-check.md`](../docs/research/manipulation-check.md).

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

## Scope

**In:** three or four framings, the existing headline pairs, the existing sweep
personas, both presentation orders, position bias per framing, and the write-up.
Roughly a few hundred votes — under ten minutes now that collection is concurrent.

**Out:** whether any framing predicts real click-through. That is validation against
field outcomes and is out of scope on the map.

## Code this needs

One small change: the task text is hardcoded inside `build_vote_messages`, so the
question sentence has to become a parameter with the current wording as its default.
Same shape as the `render_demographics_prompt` extraction 014 needed — production
keeps its behaviour, and the experiment gets a seam rather than a second copy of the
prompt that can drift.

## Consumers of the answer

- **[009](009-build-bayesian-layer.md)** — what the reported quantity is called.
- **[011](011-build-report-ui.md)** — whether the report has to carry a
  framing-dependence caveat.
- **[002](002-decide-vote-schema.md)** — the question is part of the vote contract;
  it currently specifies a content-based reason and positional voting but says
  nothing about the question itself.
