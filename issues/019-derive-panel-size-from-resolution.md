---
title: "Derive the panel size from the resolution the customer asks for (v2)"
labels: [wayfinder:grilling]
blocked_by: [020-probability-not-label]
assignee: null
status: open
---

## Question

Today a panel size is a config profile — 25, 100 or 200 — chosen by us. **Should it instead
be derived from a number the customer states: the smallest preference gap they would act on?**

## Why the current shape is wrong

The project answers *"what difference matters?"* **twice**, in two units, and never
reconciles the two answers:

- the **ROPE**, ±7 preference points — "differences smaller than this are not worth acting on"
- the **panel size**, 200 personas

Both are answers to one question, chosen independently. That is exactly why nobody noticed
they disagreed: at n=200 with ±7, `practical_tie` is reported on only **~5.6%** of genuinely
tied panels, so the ROPE's third outcome was almost absent from the product. The mismatch was
not a bug anybody wrote — it fell out of picking two numbers separately.

## The arithmetic that links them

For the credible interval to fit inside the band — the condition that makes all three
outcomes reachable — the panel size follows from the band's half-width *w* in points:

**n ≈ (98 / w)²**

because a 95% interval half-width is ≈ `98/√n` points for a proportion near even. Measured
against the real HDI, at $0.000536/vote:

| "I'd act on a gap of…" | n (tie reachable) | cost | n (tie reliable, ≥50%) | cost | runs in $10 |
|---|---|---|---|---|---|
| ±20 pts | 22 | $0.012 | 40 | $0.021 | ~466 |
| ±15 | 40 | $0.021 | 76 | $0.041 | ~245 |
| ±10 | 94 | $0.050 | 164 | $0.088 | ~113 |
| ±7 | 194 | $0.104 | 344 | $0.184 | ~54 |
| ±5 | 382 | $0.205 | 696 | $0.373 | ~26 |

**Quadratic.** Halving the gap you want to resolve costs 4×, which is the whole reason this
has to be a stated business requirement rather than a slider — nobody chooses "more
precision" rationally while the price is invisible.

## The trap this must not fall into

The derivation is sound in one direction only:

**business judgement → ROPE → n → cost.** Sound. The customer knows what gap would make them
switch headlines.

**cost → ROPE.** Not sound, and it is the same reverse-engineering that was rejected when the
question was "should we just widen the ROPE so a tie fits at n=200?" A band means *"this
difference is negligible"* — a claim about readers, not about a budget.

So the interface must never present the ROPE as a cost control. If the resolution someone
wants is unaffordable, the honest response is **"this test costs more than your budget"**, not
"lower your standard". Getting this wrong turns a principled design into a way of talking
customers into worse statistics.

## Decisions this ticket has to make

- **Which column is the default** — the minimum n where a tie is *technically* reachable, or
  the ~1.8× where it is reachable half the time. The minimum reproduces the 5.6% problem at
  every width, just relocated, so shipping it as the default would re-import the bug this
  ticket exists to remove.
- **The defensible range of *w*.** A ±25 band asserts that a 25-point preference gap is
  negligible, which no marketer believes. Somewhere around ±5 to ±15 is arguable; outside it
  the honest label is "demo", not "verdict".
- **What a per-test ROPE does to comparability.** `_ROPE` is a module constant today, so every
  verdict in the system is measured against the same band. Per-test bands mean two tests'
  verdicts are no longer directly comparable, and the report has to say which band it used —
  `PanelVerdict` already carries `rope` for exactly this reason.
- **Whether the customer states the band or the resolution.** They are different numbers
  (MDE ≈ ROPE + interval half-width), and asking for the wrong one by name would silently
  size the panel for a tighter or looser test than intended.

## The dependency that makes this cheap

**Blocked on [020](020-probability-not-label.md).** Once the verdict is a probability rather
than a three-way label, nothing has to be *reachable* for a report to be informative — a
small panel reports a lower probability and a wider interval, with no cliff and no missing
outcome. That removes the urgency from this ticket and makes it a pricing feature rather
than a correctness fix, which is why it is v2.

It also removes a blocker in the other direction: a variable band would invalidate
`_CONFIRMATIONS = 3` in [010d](010d-adaptive-stopping.md), which was simulated at ±7 (false
`decisive` on a tied panel held to 1.2% over 600 panels). A stopping rule on a continuous
probability does not have that per-band calibration problem.

## Not in scope

The v1 profiles (`dev` 25 / `demo` 100 / `prod` 200) stay as they are; see `config.py` and
[010c](010c-panel-test-pipeline.md). This ticket replaces them with a derivation, it does not
retune them.
