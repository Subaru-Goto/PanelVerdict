# Adaptive stopping: the rule's error rates and savings, simulated before it spends

**Date:** 2026-07-28, corrected same day (see the correction note) · **Harness:**
`backend/experiments/stopping_rule.py` (no model calls; binomial paths through the
production `stopping_decision` via a lookup table, so what is simulated is exactly what
ships) · **Settings:** chunk = `VOTE_CONCURRENCY` (25) and cap = the prod profile size
(200), both imported rather than restated; bar = `credible_mass` 0.95; band ±7 ·
20,000 runs per cell, seed 0.

## The question

Checking the posterior at every chunk boundary is sequential peeking, which inflates
false stops. 009 paid for that with `_CONFIRMATIONS = 3` agreeing labels, simulated at
the ±7 band, holding false decisives on a tied panel to **1.2%** — the only such
tolerance this project has ever signed off. Rule B (stop when `max(P_worth_acting)` ≥
bar, or `P_practical_tie` ≥ bar) replaces the labels, so it owes its own reading against
the single-look-at-cap baseline: same posterior, same bar, no peeking.

## Correction on the record

The first version of this table reported single-look false-decisive at a true tie as
2.3% — equal to the sequential rate — and concluded peeking was free. That was a bug:
stopped runs froze their vote counts, and the baseline indexed the cap row with those
partial counts, silently replaying the sequential stops into the "no peeking" column.
The corrected baseline draws every run to the cap. The conclusion below **reverses** the
original: peeking is not free at this bar, and the no-confirmation design chosen on the
buggy table was revised to two confirmations. Kept here because the wrong version
briefly justified a shipped decision, and the correction is the evidence for the fix.

## The corrected table

```
true_p  conf  stop%   E[votes]  decisive%  tie%   wrongdir%  single-look%
0.50    1     0.023    196.3     0.023     0.165   0.023      0.000
0.55    1     0.073    190.1     0.075     0.060   0.002      0.014
0.57    1     0.140    182.5     0.148     0.025   0.001      0.047
0.60    1     0.337    161.4     0.364     0.003   0.000      0.214
0.65    1     0.783    107.4     0.826     0.000   0.000      0.747
0.70    1     0.986     61.0     0.993     0.000   0.000      0.987
0.50    2     0.004    199.4     0.004     0.000   0.004      0.000
0.55    2     0.029    196.8     0.031     0.000   0.000      0.013
0.57    2     0.073    193.0     0.080     0.000   0.000      0.052
0.60    2     0.212    180.8     0.240     0.000   0.000      0.216
0.65    2     0.666    137.0     0.731     0.000   0.000      0.752
0.70    2     0.961     91.3     0.980     0.000   0.000      0.987
0.50    3     0.001    199.9     0.001     0.000   0.001      0.000
0.55    3     0.015    198.7     0.017     0.000   0.000      0.013
0.57    3     0.039    196.9     0.046     0.000   0.000      0.049
0.60    3     0.140    189.3     0.171     0.000   0.000      0.209
0.65    3     0.548    157.6     0.632     0.000   0.000      0.752
0.70    3     0.915    116.7     0.954     0.000   0.000      0.984
```

## What it settled

**Two consecutive confirming boundaries (`_STOP_CONFIRMATIONS = 2`).**

- A single crossing calls a false decisive on **2.3%** of genuinely tied panels against
  a single-look baseline of **~0.03%** — roughly 77× inflation, and above the 1.2% the
  project accepted for the old rule.
- Two crossings hold it to **0.4%**, under that precedent, while keeping the savings —
  E[votes] **137** at a true 65/35 (32% of the cap saved), **91** at 70/30 (55%) — and
  matching single-look power on real leads (73.1% vs 75.2% decisive at 65/35).
- Three crossings buy little (0.1%) and cost real power: 63.2% at 65/35, well under the
  baseline's 75.2%, with savings shrinking to 21%.

**The tie stop is illusory at these settings, and that is worth saying plainly.**
`P_practical_tie ≥ 0.95` first becomes reachable around n=200 — the cap itself — so a
"tie stop" never saves a vote and can never accumulate two confirmations. The tie clause
stays in the rule (a wider band or a larger cap would make it real), but equivalence
remains cap-priced, and the report's own probabilities carry the tie finding at render
time regardless of `stop_reason`. The first version's argument that confirmation "kills
the tie stop" was true and irrelevant.

**Costs, stated:** at the band edge (p=0.57, where "worth acting on" is a coin flip by
construction) two-confirmation sequential calls decisive 8.0% against the baseline's
5.2% — the residual peeking cost, accepted.

## Relation to `_CONFIRMATIONS = 3`

That constant guarded the label-agreement rule and died with it (010d deleted
`panel_progress` and friends). Its simulated tolerance — 1.2% false decisive on a tied
panel — survives as the yardstick this table was read against.
