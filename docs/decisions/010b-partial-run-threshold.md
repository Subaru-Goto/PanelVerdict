---
title: "Decide the partial-run threshold: when is a thinned panel still a verdict?"
labels: [wayfinder:grilling]
parent: 010-assemble-orchestrator-graph
blocked_by: [010a-vote-usage-instrumentation]
assignee: Subaru-Goto
status: closed
---

## Question

A run asks for 200 personas and reaches the posterior with fewer. **At what point does the
report stop offering a verdict, and what does it say instead?**

[003](003-decide-panel-model-and-provider.md) requires *"mark run **partial**, never emit a
half-panel"* and nothing has set the line. This is a decision ticket because the answer is a
product judgement about what a customer may be shown, not a mechanism.

## The panel thins twice, and it compounds

1. **Retrieval matched fewer than asked.** A trait filter multiplies: `very_high` on two
   traits is ~0.4% of the population, so a 5,000-pool yields ~22 personas
   ([017](017-representative-sampling.md)). `PanelSelection.notices` carries the warning.
2. **Votes failed.** `collect_panel_votes` returns `PanelVotes(records, failures)`
   ([008](008-build-panel-evaluation.md)); a failed vote costs that panelist and no other.

So three numbers exist — **requested, matched, voted** — and the verdict rests on the third.
Today nothing stops a 22-persona verdict being presented like a 200-persona one.

## What makes a line defensible

The statistics already say something concrete, and it is the natural place to anchor:

> **Both bullets below are wrong, and the correction is this ticket's main finding
> (2026-07-28).** The ~1,100 figure was 009's **±3** requirement, not ±7; at ±7 a tie becomes
> expressible at n=194. But the real error is the other way round: `practical_tie` is reported
> on only **~5.6%** of genuinely tied panels at n=200, so it is ~94% unavailable *at full
> size*. Thinning cannot remove an outcome that was never reliably there, so this cannot be
> the basis for a floor. See the resolution below.

- At the ±7 ROPE, `practical_tie` needs roughly **1,100 votes** to be expressible at all
  ([009](009-build-bayesian-layer.md)). Below that, one of three outcomes is unreachable —
  and a verdict that *cannot* return `practical_tie` is not a weaker verdict, it is a
  differently-shaped one.
- So a thin panel does not merely widen the interval. It changes **which conclusions are
  available**, which is why "just show the wider interval" is not automatically the answer.

Candidate shapes, none yet chosen:

| shape | what it costs |
|---|---|
| Absolute floor (e.g. refuse under *n*) | Simple and explicable, but any *n* is arbitrary unless derived from interval width |
| Fraction of requested (e.g. under 50% → partial) | Scales with the ask, but says nothing about whether the verdict is readable |
| Derived from the posterior — refuse when the interval exceeds some width | Honest, and it is the quantity that actually matters; harder to explain to a customer |
| Never refuse; always report all three counts and the interval | Maximum honesty, zero paternalism — and it relies on the reader understanding a CrI |

The last one deserves a fair hearing rather than being dismissed: this project's own house
style has repeatedly chosen "report the fact, let the caller decide"
(`PanelVotes.failures`, `PanelSelection.notices`, `VoteTally` refusing to name a winner).
A refusal threshold is a departure from that, so it needs a reason — probably that a
*verdict* is a stronger speech act than a tally, and the report leads with it.

## Also to decide

- **Does `retrieval` thinning and `vote` thinning get treated the same?** A target that
  matched 22 personas got what the pool could give; a run that lost 40 votes to 429s is a
  transient failure that a re-run might fix. Same number, different remedy — so possibly
  different messages.
- **What does "mark partial" mean concretely** — a field on the payload, a different
  outcome value, or the absence of a verdict? [011](011-build-report-ui.md) has to render it.
- **Is a partial run cached and resumable** ([010e](010e-per-vote-cache.md)), so that
  topping up the budget completes it rather than restarting it?

## Why it waits on [010a](010a-vote-usage-instrumentation.md)

Because "re-run it" is only sound advice if a re-run is affordable, and the per-test cost is
currently unmeasured. If a 200-vote run turns out to cost materially more than the retracted
estimate, "resume the partial run" (010e) becomes the primary remedy and refusing outright
becomes expensive — which changes the answer to this question rather than merely informing it.

## Not to be decided by guessing

The failure *rate* is unmeasured — no real 200-vote run has happened. So this ticket should
set a line from the **interval mathematics**, which is already known, rather than from an
assumed failure frequency. If it finds itself needing a failure rate, that is a signal to run
[010c](010c-panel-test-pipeline.md) first and come back.

## Resolved 2026-07-28 — no threshold, and the customer is informed instead

**Decided with the user: there is no partial-run threshold.** Every run that produces at
least one vote returns a verdict. The only refusals are the two degenerate cases
[010c](010c-panel-test-pipeline.md) already shipped — `matched = 0` is 422 (nobody to ask)
and `voted = 0` is 502 (nobody answered) — and neither is a threshold; both are arithmetic.

**Why the question dissolved rather than got answered.** The four candidate shapes above
were written when the verdict was a three-way label, and a threshold's job was to stop a
thin panel overclaiming. The overclaiming lived in the *label* — "decisive" on 22 votes
reads like "decisive" on 200 — and [020](020-probability-not-label.md) removed the label.
Every quantity in the payload now carries its own uncertainty: the probabilities widen with
few votes because that is what the posterior does, `detectable_gap` states what the size
can resolve, and the three counts sit beside them. The half-panel [003](003-decide-panel-model-and-provider.md)
forbade was a *disguised* thin panel; the disguise is no longer constructible.

**The lines that remain are all derived, none legislated:**

- `detectable_gap` is `None` below n=5 — the mathematics' own statement that no split could
  have been decisive.
- Below n=5 no unanimous panel clears `credible_mass`, so the render-time recommendation
  reads "no call" without a rule saying so.
- Any legislated floor between those and 194 would be an unsourced constant.

**The accepted edge, stated rather than hidden:** at n=5 a unanimous panel reaches
P=0.966 and the headline calls it. That is the honest Bayesian answer to five-of-five, and
it renders beside "5 voted" and a ±36-point resolution. If it needs softening, that is a
presentation judgement belonging to [011](011-build-report-ui.md), not a compute-time gate.

**"Mark partial" concretely = the counts plus the notices, no boolean.** `voted < matched`
is derivable from data the payload already carries; a stored flag would be a label again.
The two thinnings now read differently because their remedies differ:

- *Retrieval shortfall* (already existed): the pool gave what it could — re-running
  changes nothing; broaden the target or grow the pool.
- *Vote shortfall* (**built with this decision**): `_vote_shortfall_notice` in
  `app/pipeline.py` — "N of the M matched panelists did not vote… transient — a re-run may
  recover them." `PanelTestResult.notices` is the complete set (selection's plus the
  run's own), the same one-place-to-look rule `PanelSelection.notices` already followed,
  and `/evaluate` forwards it.

Renamed `TargetNotice` → `Notice`: the moment a vote failure joined the list, the type
stopped being about how the target was read.

Deferred with owners: resume-instead-of-re-run is [010e](010e-per-vote-cache.md)'s (the
notice's wording upgrades when it lands); rendering the informing is [011](011-build-report-ui.md)'s.

414 tests green (+2), ruff check and format clean.
