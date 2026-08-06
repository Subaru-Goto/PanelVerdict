---
title: "The analyst's cost is unmeasured, and no usage reaches the wire"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Goal

Make spend visible. [064](064-the-cost-ceilings.md) signed off a $1.00/day ceiling that bounds
**panel** spend and is blind to **chat** spend, because nothing measures the latter.

### Two findings

- **The analyst's cost has never been measured.** `docs/research/` mentions the analyst only
  inside `panel-model-selection.md`, and **no `usage` field exists on the wire** —
  `pipeline.py:316` builds `UsageTotals` and `EvaluateResponse` (`schemas.py:482`) never
  carries it. So a conversation's cost is currently unknowable.
- **A model decision fell through a gap.** `003:38`: *"**Analyst model:** a reasoning model —
  separate role/run, so its selection is deferred to **012**."* 012 shipped, and
  `config.py` carries `analyst_model = "openai/gpt-5.6-luna"` — the panel's model, with no
  `reasoning_effort` set. No record shows the pick was made. Recorded so it stops being
  invisible.

## The cheapest lever is already measured, and it is not a different model

`panel-model-selection.md:59`:

> *"**`reasoning_effort=low` halves the bill** ($0.057 vs $0.107 per test) and cuts latency by
> 44%, with no parse failures at this sample size. It is **not adopted**: effort changes what
> the panel is, and the measured first-position rate and question-wording sensitivity were both
> taken at the default."*

**Every one of those objections is about the panel, and none applies to the analyst:**

- the vote fingerprint covers votes, so nothing is re-keyed
- 014 and 015 measured the panel, so no published result is invalidated
- an explainer has no first-position rate and no question-wording sensitivity to preserve

So a **2× saving is available on the analyst at no invalidation cost** — strictly better than
switching to an unknown cheaper model, which would trade a measured lever for an unmeasured one.

**The one real risk, and it is CI-invisible.** The analyst's value rests on obeying the
two-kinds rule — *"never from memory, never estimated."* `025:113` records that prompt
obedience is **unassertable by the test suite**, because `ScriptedChatModel` picks the tool on
the model's behalf. So lower effort degrading obedience shows up as invented figures with **no
test going red**. Whatever ships needs a live check, not a suite run.

## Scope

- **`UsageTotals` on the wire.** The pipeline already builds it; `EvaluateResponse` does not
  carry it.
- **Analyst usage captured per turn**, so chat spend is knowable. The stream is NDJSON events,
  so where a total lands in that contract is a design question rather than an append.
- **Try `reasoning_effort=low` on the analyst** and measure both halves: the saving, and
  whether the two-kinds rule still holds under it.
- **Show cost in the report.** Restyle-only constraints apply — no information-architecture
  changes.

This is also close to the assignment brief's *"display token usage and costs"* medium task. The
brief lives on the submission remote as `125.md` rather than in this repo, so treat the wording
as approximate until checked there.

## What it does *not* need to establish

**The per-vote cost is already settled** and an earlier draft of this ticket wrongly called it a
contradiction. `panel-model-selection.md:39`'s **$0.000536** is 010a's superseded 10-vote
figure: `first-full-scale-run.md:22` is headed *"Cost at scale: $0.00069/vote, superseding 010a's
$0.000536"* and gives the reason — output ran ~310 tokens/vote against 010a's 234. `config.py:47`
then documents choosing **the higher** at-scale reading, $0.000726 over 50 votes against
$0.000687 over 200, *"so the pre-flight warning errs toward warning a run that would have
squeaked through."*

Recorded because two live figures that *look* contradictory will invite the same wrong
conclusion again.

## Done when

A run's usage and cost travel on the wire and appear in the report, an analyst turn's cost is
measurable, and `reasoning_effort` for the analyst is either adopted with its obedience checked
live or rejected with a reason.
