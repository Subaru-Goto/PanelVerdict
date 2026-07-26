---
title: "Build the Bayesian layer (flat Beta-Binomial + full report + adaptive stopping)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [002-decide-vote-schema]
assignee: null
status: open
---

## Goal

Pure-Python, deterministic — **no LLM** touches the statistics:

- flat binary Beta-Binomial (SciPy, conjugate — no sampler),
- full posterior report: **P(B>A)**, expected lift + 95% credible interval, **expected loss**, **ROPE** verdict (±3 pts → "practical tie — pick either or test a bolder variant"),
- **adaptive stopping**: update posterior per batch, stop at the P-threshold or the budget cap,
- neither-rate passed through descriptively (not modeled).

## Amended 2026-07-26 — the design is a paired comparison, and "lift" must be renamed

**One panel sees both variants and each persona makes a forced binary choice.** This
is a paired comparison, not a two-arm A/B test where separate groups each see one
variant and CTRs are compared. Three consequences, and the third is the one that can
cause real damage:

1. **There is no second arm, by construction.** Each persona compares the variants
   itself, so between-person variation cancels — every respondent is its own control.
   That is why [007](007-build-targeting-query-translation.md) drops the per-test
   control group: there was never an arm structure to put one in.
2. **One parameter, and it is already what this ticket says.** `p = P(prefers B)`,
   `k` of `n` votes for B, flat Beta prior. So **`P(B>A)` is exactly the posterior
   mass above 0.5**, and the ±3pt ROPE is a band around 0.5. Also why a ~200-persona
   panel suffices where a two-arm CTR test would need thousands.
3. **"Expected lift" is two-arm vocabulary and will be misread as CTR lift.** Here it
   can only mean `E[p] − 0.5`, in **preference-share points**. It is *not* a predicted
   click-through difference, and the two are not interchangeable: in the wild almost
   nobody sees both headlines, so real users never make the comparison the panel just
   made. Forced choice is a far sharper instrument than field behaviour, and a strong
   preference share can sit on top of a small click difference.

So the reported field is a **preference share**, named as such — never a bare "lift".
A marketer who reads "70% lift" as CTR will forecast revenue off it, which is the one
number in this stack capable of producing a confidently wrong business decision. This
is a naming and labelling requirement on the API payload, not only on the UI
([011](011-build-report-ui.md) carries the display half).

Not addressed here, and not this ticket's to fix: whether panel preference *predicts*
field behaviour at all. That is the Upworthy validation study, out of scope on the map.