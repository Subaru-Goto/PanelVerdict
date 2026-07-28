---
title: "Report the ROPE as a probability, not a three-way label"
labels: [wayfinder:task]
blocked_by: []
assignee: null
status: closed
---

## Goal

Add **`P(the preference share falls outside the ROPE)`** to `PanelVerdict`, keep
`practical_tie` as a flag, and stop storing `undecided` as the answer.

This is not a new idea. `docs/project-idea.md:125` specifies *"P(the preference share falls
outside the ROPE)"* as a report output; [009](009-build-bayesian-layer.md) built the
three-way categorical `rope_verdict` instead, and the substitution was never noticed.

## Why the label is worse than the number

`rope_verdict` compares the credible interval to the band and returns one of
`decisive | practical_tie | undecided`. At n=100:

| split | `rope_verdict` | **P(B better *and* worth acting on)** | shortfall from shipping A |
|---|---|---|---|
| 50/100 | `undecided` | 0.078 | 1.97 pts |
| 55/100 | `undecided` | 0.337 | 5.32 pts |
| 58/100 | `undecided` | 0.572 | 7.96 pts |
| 60/100 | `undecided` | 0.721 | 9.85 pts |
| 63/100 | `undecided` | 0.884 | 12.75 pts |
| 65/100 | `undecided` | **0.946** | 14.71 pts |
| 67/100 | `decisive` | 0.978 | 16.67 pts |

**At 65/100 the label says "undecided" while the data says 94.6%.** The label is not merely
imprecise there — it withholds a recommendation the evidence supports, and it does so across a
15-point range, because one word stands in for everything between dead-even and near-certain.

`undecided` is also the **modal** outcome: on a genuinely tied pair at n=200 it fires ~94% of
the time, because `practical_tie` needs the interval wholly inside the band and that happens
at ~5.6% of splits. So the bucket that carries the least information is the one the product
returns most often.

## What stays, and why the band cannot simply go

**The ROPE itself is load-bearing.** Without a band, `probability_majority_prefers_b` is a
claim about *direction only* — at a true 50.5/49.5 split it would eventually read as a
confident win. The band is what turns "different" into "different enough to act on", which is
the only form a marketer can use. It is also a named graded requirement twice over
(`project-idea.md:130`, `:164`), so removing it would drop a deliverable.

**`practical_tie` stays too**, as a flag rather than one of three exhaustive buckets. *"These
are equivalent — pick either, or test a bolder variant"* is a positive finding that nothing
else in the layer can assert, and it is worth reporting on the ~6% of runs where it holds.

**`undecided` is the part that goes.** It conflates two opposite situations — "these are
equivalent" and "we do not have enough data" — and the continuous probability distinguishes
them by construction.

## Design

- **Add** `probability_worth_acting_on_b: float` to `PanelVerdict` — `P(share > rope_high)`.
  Two Beta CDFs, closed form, the same shape `expected_preference_shortfall` already uses; the
  mirror `P(share < rope_low)` is the same call and worth exposing if the report reads both
  directions.
- **Add** the panel's **resolution** — the smallest gap this *n* can call decisive — computed
  from `n` and the band rather than stored. It is currently a comment in `config.py` next to
  the profiles, which is a number that can drift from the table beside it. [011](011-build-report-ui.md)
  needs it to make a thin panel's `undecided`-shaped result self-explaining: *"this panel could
  detect a gap of 26 points or more; it did not find one."*
- **Keep** `practical_tie` as a boolean.
- **Retire** `undecided` as a stored outcome. A recommendation becomes something the report
  derives from the probability against a stated threshold at render time, so the plain-English
  headline survives and the quantity underneath is no longer thrown away.

## Knock-on

- [011](011-build-report-ui.md) renders the new fields, and gains the resolution sentence.
- [012](012-build-analyst-chatbot-tools.md)'s `analyze_results` tool lists "ROPE verdict"
  among its outputs; it should return the probability, which is what a question like *"how
  confident should I be?"* actually needs.
- [010d](010d-adaptive-stopping.md) gets a better stopping signal: one continuous quantity
  crossing a threshold, rather than `_CONFIRMATIONS = 3` agreeing labels — a rule that had to
  be simulated at one specific band width and would need re-simulating for any other.
- [019](019-derive-panel-size-from-resolution.md) is unblocked by this: once nothing has to be
  *reachable*, a small panel is informative rather than broken, and sizing becomes a pricing
  decision instead of a correctness one.

## What this does not change

The ROPE stays at **±7** and the profiles stay at 25 / 100 / 200. This ticket changes how the
verdict is *reported*, not what counts as a meaningful difference.

## Closed 2026-07-28

`PanelVerdict` carries `probability_worth_acting_on`, `probability_practical_tie` and
`detectable_gap`; `outcome` is gone from the payload. `rope_verdict` itself stays, for
`_CONFIRMATIONS = 3` only — counting batches *agreeing* needs something discrete to compare,
and there the coarseness costs a batch rather than a recommendation. This does **not**
pre-decide [010d](010d-adaptive-stopping.md), which may well replace the label with a
continuous quantity crossing a threshold; it keeps working what already works.

`undecided` is retired as a *stored* answer, which is what the ticket asked. It survives on
`Batch.verdict`, which has no caller outside `verdict.py` today — but [011](011-build-report-ui.md)'s
batch-streaming progress is where that stops being true, so the label needs a decision there
rather than an assumption that it is already private.

`detectable_gap` computes from *n* and the band, so `config.py`'s per-profile ±26/±17/±14
figures are **deleted rather than recomputed there**: a resolution beside the table would
outlive a change to either input, and putting it *in* config would make the settings module
import SciPy for a number nothing in config reads. The measured costs stay in that comment,
since nothing derives them.

Three deviations from the ticket as written:

1. **`practical_tie` is a probability, not a boolean.** The ticket said "keep it as a flag";
   a flag bakes a threshold in at compute time, which is the exact thing this change is
   against. `probability_practical_tie` is the same assertion with the number left attached.
2. **Both directions ship, not just B.** The ticket specified
   `probability_worth_acting_on_b: float` and noted the mirror was "worth exposing if the
   report reads both directions" — it does, so the field is a `PreferenceExposure` with the
   same `shipping_a` / `shipping_b` names `expected_preference_shortfall` already uses.
3. **The frontend moved too, because it was reading `outcome`.** Removing the field would
   otherwise have rendered a blank headline rather than failing. The recommendation is derived
   at render time and the bar is the verdict's **own `credible_mass`** — the one credibility
   the payload already states — because any other number would be one nobody signed off. It is
   printed beside the two probabilities, since the ticket asked for a *stated* threshold and a
   bar the reader cannot see is the same withholding in a smaller form. Consequence worth
   knowing: at 65/100 the headline still declines to call it, since 0.946 is under 0.95. The
   difference is that the 0.946 is now on screen next to it, which was the complaint.

`probability_worth_acting_on` gets its **own type** rather than reusing `PreferenceExposure`.
The two are structurally identical and differ only in unit — probability in 0-1 against
preference-share points — and the frontend picks the formatter by hand, so a reader that
formatted 0.95 as "95 points" would be wrong by the width of the scale.

401 tests green (+2), `tsc --noEmit` and eslint clean.
