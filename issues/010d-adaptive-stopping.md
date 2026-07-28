---
title: "Adaptive stopping: vote in chunks and stop when the posterior is decided"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: [010c-panel-test-pipeline]
assignee: Subaru-Goto
status: closed
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

## Closed 2026-07-28

The loop ships, and the stopping rule is **not** the sketch above. Rule chosen (with the
user, over label agreement): **stop when the report would already make a call** —
`max(P_worth_acting_on) ≥ credible_mass`, or `P_practical_tie ≥ credible_mass`. The bar is
`credible_mass` itself, so the run stops exactly when the render-time recommendation would
fire and no second threshold exists to source. This answers the ticket's own warning — a
rule that never stops on a tie always burns the cap — which the label rule suffered from,
since three consecutive `practical_tie` labels effectively never occur (~5.6% each).

**Simulated before it spent anything** ([adaptive-stopping.md](../docs/research/adaptive-stopping.md),
20k runs/cell through the *production* decision function via a lookup table) — **and the
first version of that simulation was wrong in a way that changed the design.** Its
single-look baseline replayed the sequential stops into the "no peeking" column, which
made peeking look free; the review caught it, and the corrected table reversed the
conclusion:

- **Two consecutive confirming boundaries (`_STOP_CONFIRMATIONS = 2`), not none.** A
  single crossing calls a false decisive on 2.3% of genuinely tied panels against a
  corrected single-look baseline of ~0.03% (≈77× inflation, above the 1.2% the project
  accepted when it simulated the old label rule). Two crossings hold it to 0.4% and
  match single-look power on real leads. A streak is broken by a boundary that reads
  differently — including a decisive that flips direction.
- **Savings, corrected:** E[votes] 137 at a true 65/35 (32% of the cap), 91 at 70/30
  (55%). A clear winner costs ~$0.05–0.07 instead of $0.107.
- **The tie stop is illusory at these settings:** `P_tie ≥ 0.95` first becomes reachable
  at the cap itself, so it never saves a vote. The clause stays for generality; the
  report's probabilities carry the tie finding at render time regardless.
- **Costs, stated:** at the band edge, confirmed-sequential calls decisive 8.0% vs 5.2%
  single-look — the residual peeking cost, accepted.

**Decisions the ticket listed, dispatched:**

- *Chunk size:* `VOTE_CONCURRENCY` (25) — not a new constant; no worker idles mid-chunk,
  and the dev profile degenerates to today's single fan-out.
- *Early stop vs shortfall:* an early stop is a **fact**, carried two ways — `stop_reason`
  on the result and the payload (data for [011](011-build-report-ui.md)), and a
  `reading`-severity notice ("Stopped after 50 of the 75 matched panelists: the panel had
  already decided…"). Failed votes stay a `warning`. The notice guards on panelists going
  *unasked*, not on the vote count — a stop firing on the final boundary with a few failed
  votes left nobody unasked, and "the remaining votes would not have changed the call"
  must never be said about votes that merely failed. Opposite situations, opposite
  severities, per [010b](010b-partial-run-threshold.md)'s informed-not-refused rule.
- *Measurement:* the savings number the ticket wanted came from the simulation, free. The
  paired **real** run (fixed 200 vs stopped, ~$0.21) remains a deliberate spend decision,
  still owed alongside [010f](010f-budget-guard.md)'s latency reading.

**Removed as dead code:** `panel_progress`, `PanelProgress`, `Batch`, `_confirmed`,
`_CONFIRMATIONS` and their tests — the loop replaced their only purpose. `rope_verdict`
survives with one caller left, `detectable_gap`'s boundary test. Note for
[011](011-build-report-ui.md): the narrowing animation that `PanelProgress` was built for
can be replayed from the ordered vote records; nothing was lost, but the pre-chewed
per-batch structure is gone and 011 should plan to derive it.

419 tests green, ruff check and format clean.
