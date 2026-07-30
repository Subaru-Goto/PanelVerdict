---
title: "The report prints 100% for a probability that is 0.99999 — rounding invents a certainty"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found in real use, 2026-07-30)

A 25-panelist test split **A 23 · B 2** rendered *"Chance A is preferred:
**100%**"*. The user caught it reading the chart caption beside it.

The backend is right; the display is not. Run through the real function:

```
panel_verdict(preferring_b=2, total=25)
  P(majority prefers B) = 5.245208740234375e-06
  P(majority prefers A) = 0.9999947547912598
```

`formatPercent` is `(value * 100).toFixed(0)`, so 99.99948 → `"100%"`. The
same rounding hits the other end: 5.2e-06 renders `"0%"`, i.e. impossible.
And it is not one field — `probability_meaningfully_preferred.a` was
`0.99990759` on the same run, also `"100%"`.

## Why this is worth a ticket and not a shrug

A Beta posterior **cannot reach 0 or 1**. Printing `100%` claims a certainty
the panel mathematically does not have, from 25 synthetic votes — which is
precisely the overclaim this layer was built to avoid.
[020](020-probability-not-label.md) removed the categorical verdict for
collapsing a 15-point range into one word; rounding collapses the top of the
range into a *falsehood*. [011](011-build-report-ui.md)'s cold-reader rule
applies directly: a reader who does not know the answer reads `100%` as
"settled", and nothing on the screen contradicts them.

## Fix

One place — `formatPercent` in `app/lib/format.ts`. Rewrite only the artifact:
when the rounded value lands on 0 or 100 but the true value is strictly inside
(0, 1), render `<1%` / `>99%` instead.

Checked before choosing to clamp in the shared formatter: **every** quantity it
formats is a posterior mean, a probability, or an HDI bound — all strictly
inside (0, 1) by construction — so a rendered `0%`/`100%` is always wrong
there, and no legitimate case is broken. An exact 0 or 1 still renders as
itself rather than being rewritten, so the guard states a fact about the value
rather than an assumption about the caller.

`formatPoints` is left alone: points are differences, where 0.0 is a real and
reportable reading.

## Out of scope, noted

The analyst reads the same probabilities as raw floats and could round them
into the same claim in prose. Its prompt says plain language but says nothing
about never asserting certainty. That is prompt work, unassertable by the
suite, and belongs with the other judge-territory items rather than here.

## Related

- [020](020-probability-not-label.md) — the ticket that removed the previous
  overclaim, for the same reason in a different disguise.
- [011](011-build-report-ui.md) — the cold-reader standard this fails.
