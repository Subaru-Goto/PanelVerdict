---
title: "Decide the partial-run threshold: when is a thinned panel still a verdict?"
labels: [wayfinder:grilling]
parent: 010-assemble-orchestrator-graph
blocked_by: [010a-vote-usage-instrumentation]
assignee: null
status: open
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
