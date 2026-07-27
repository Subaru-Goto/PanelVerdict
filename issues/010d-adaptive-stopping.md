---
title: "Adaptive stopping: vote in chunks and stop when the posterior is decided"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: [010c-panel-test-pipeline]
assignee: null
status: open
---

## Goal

Turn 010c's single full panel into a loop: vote a chunk, update the posterior, stop when the
question is answered or the budget cap is reached.

```python
while undecided(posterior) and voted < max_n:
    votes = collect_panel_votes(panel[voted:voted + step], ...)
    posterior = update(posterior, votes)
    voted += step
```

This is the whole of what LangGraph's *"adaptive-stopping conditional edge"* was going to be
(see 010's decision). [009](009-build-bayesian-layer.md) chose a conjugate Beta-Binomial
specifically so a chunk update is `a += k; b += n - k` rather than a re-fit — the arithmetic
is already there.

## Why it earns its own ticket

It is the only non-linear part of the pipeline, and it is where the run stops being one
transaction. Two things change the moment the loop exists:

- **A run has intermediate states**, so it can be stopped, resumed
  ([010e](010e-per-vote-cache.md)), and reported on while in progress
  (*"87/200 personas voted…"*, which [011](011-build-report-ui.md) wants).
- **The chunk boundary becomes the natural checkpoint** — the thing
  [008](008-build-panel-evaluation.md) deliberately does not have, since it fans out with a
  concurrency cap rather than discrete batches. [010f](010f-budget-guard.md)'s mid-run 402
  stop lands here or nowhere.

## Decisions this ticket has to make

**The chunk size, and it is a real trade-off.** Small chunks stop earlier on an obvious
winner (cheaper) but barrier more often, so the fan-out idles at each boundary. Large chunks
keep the pool busy but overshoot the stopping point. 008's concurrency is 25, so a chunk that
is not a multiple of it wastes workers.

**The stopping rule.** 009 specifies *"stop at the P-threshold or the budget cap"* — so the
threshold on `probability_majority_prefers_b`, or on interval width, and which one. Note the
interaction with the ROPE: a run can be confidently *inside* the ROPE (a real
`practical_tie`) and that is a **stop**, not a continue. A rule written only as
"P > 0.95 or P < 0.05" never stops on a tie and always burns the full cap.

**What the early stop does to the counts.** 010c reports requested / matched / voted; a
deliberate early stop makes `voted < requested` **on purpose**, which must not read as the
shortfall [010b](010b-partial-run-threshold.md) is about. Stopping early because the answer
is clear and stopping early because votes failed are opposite situations with the same
arithmetic — the payload has to distinguish them, or the report will call a success a
degraded run.

That last point is the one most likely to be got wrong, and it is cheap to get right if it is
decided here rather than discovered in 011.

## Measurement worth taking while here

How much does stopping actually save? One run at a fixed 200 versus the same target with
stopping enabled gives the answer, and it is the number that justifies the mechanism's
existence. Record it with the usage figures from
[010a](010a-vote-usage-instrumentation.md) — if the saving is small because most tests run to
the cap anyway, that is worth knowing before 011 builds UI around it.
