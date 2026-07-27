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

## Amended 2026-07-27 — the reported quantity is framing-bound

[015](015-task-framing-sensitivity.md) measured that changing the question sentence
flips 38–43% of matched votes, well past the ~0.21 noise floor. `preference` stays
the shipped framing — nothing in that run gives grounds to switch — but the pairing
of question to reported name is now load-bearing rather than tidy.

The panel is asked *"Which do you prefer?"*, so the payload reports a **preference
share**. It may not be named or documented as click intent, and switching the
shipped question later means renaming the field, not just changing a prompt.

### What the posterior protects against, and what it does not

Run this layer's own model over 015's negative control — the lever Gligorić's
24,333-pair field study found does *nothing* — flat Beta prior, `k` of `n` votes:

| cell | E[p] | 95% CrI | P(B>A) | ROPE mass |
|---|---|---|---|---|
| `second_person` / click | 0.892 | [0.825, 0.944] | 1.000000 | 9×10⁻¹⁶ |
| `second_person` / attention | 0.931 | [0.875, 0.972] | 1.000000 | 9×10⁻²⁰ |

Nothing is malfunctioning there. The model is doing exactly what this ticket
specifies, and it reports near-total certainty about a difference that does not
exist in the field.

State the reason precisely, because it reads like a flaw in the statistics and is
not one: **the credible interval quantifies uncertainty about the *panel's*
preference share.** Whether that share tracks readers is a different question, and
not a sampling one. Bayesian updating propagates noise correctly and cannot see
bias — the panel genuinely does prefer the "you" variant 90% of the time. Collect
more votes and the interval narrows around the same wrong value.

The noise floor does not catch it either, and fails in the worst direction: a
consistently biased model rarely flips, so the run's own reliability statistic
makes this the most trustworthy-*looking* cell in the file.

What the posterior *does* handle well is genuine indecision — a panel with no real
preference lands near 0.5 with a wide interval, and the ROPE returns "practical
tie". That is honest and it is why the design is right. The gap is narrower than
"Bayes doesn't help": it handles indecision well and confident bias not at all.

### Adaptive stopping: keep it, and record what it does not mean

Early stopping is what makes a panel affordable — paying for sixty personas instead
of two hundred when the answer is already clear. At this project's budget that is
decisive, and it is a genuine advantage of the Bayesian formulation over a
fixed-n frequentist test. Keep it.

The caveat is only about interpretation. P crossed 1.000000 by n = 100 on the
control above, so **stopping time is driven by how consistent the panel is, not by
how right it is** — a run terminates early because the panel agreed with itself.
Neither a short run nor a high P may be presented as evidence that the result is
reliable.
