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


## Amended 2026-07-27 — four decisions taken before implementation

### SciPy, not PyMC — for now

PyMC belongs to the **hierarchical** model `docs/project-idea.md` schedules for later,
where partial pooling has no conjugate solution and a sampler is genuinely required.
For the flat Beta-Binomial it would mean running MCMC to approximate a quantity that
can be written down exactly, and that costs four things:

- **Sampling error where there is none.** With a flat prior and integer counts the
  posterior is `Beta(1+k, 1+n-k)` and `P(p > 0.5)` is exact; MCMC would add noise to
  the one number that has none.
- **Reproducibility.** [002](002-decide-vote-schema.md) requires test-retest
  determinism. Sampling is reproducible only with a pinned seed *and* a pinned
  sampler version.
- **Dependency weight.** PyTensor and a compiler toolchain, against a project rule of
  adding only what is directly needed.
- **It would undercut adaptive stopping.** Conjugacy makes a batch update `a += k;
  b += n - k`, O(1). A sampler re-fits the whole posterior every batch, which is
  exactly the cost early stopping exists to avoid.

Revisit when the hierarchy arrives — that is the problem PyMC is for.

### HDI, not the equal-tailed interval

A 95% credible interval is any interval holding 95% of the posterior. The equal-tailed
one chops 2.5% from each end; the HDI is the shortest such interval, so no point
outside it is more plausible than a point inside. They coincide when the posterior is
symmetric and diverge when it is skewed:

| posterior | equal-tailed | HDI |
|---|---|---|
| `Beta(9,3)` — 8 of 10 votes | [0.482, 0.940] | [0.516, 0.959] |
| `Beta(121,81)` — 120 of 200 | [0.5307, 0.6654] | [0.5314, 0.6661] |

In the skewed row the two give **opposite answers** to "does the interval exclude a
tie?" — equal-tailed dips below 0.5, HDI does not. At n = 200 near 0.5 they agree to
three decimals.

So the choice only matters at small n or extreme splits — which is precisely where
adaptive stopping may terminate a run. Keeping early stopping is therefore the reason
to take the HDI. It is a bounded numeric optimisation over a unimodal density, and it
is testable against the property that defines it.

### Adaptive stopping fires on the *verdict*, not on P

Amended again 2026-07-27, before slice 4 was built. The natural reading of this
ticket's "stop at the P-threshold" disagrees with its own ROPE verdict
**systematically at every panel size**:

| n | first k reaching P >= 0.99 | P | HDI | ROPE verdict |
|---|---|---|---|---|
| 200 | 117 | 0.9919 | [0.516, 0.652] | undecided |
| 400 | 224 | 0.9918 | [0.511, 0.608] | undecided |
| 800 | 433 | 0.9902 | [0.507, 0.576] | undecided |
| 1600 | 847 | 0.9906 | [0.505, 0.554] | undecided |

So a run stopping the moment P crosses the bar stops and then reports *inconclusive*.
The votes are spent, the criterion is met, and the customer gets no answer.

The two rules ask different questions. `P(p > 0.5) >= 0.99` asks whether B is ahead
**at all**; the HDI against the ROPE asks whether B is ahead **by enough to matter**.
The second is strictly stronger, so it needs more evidence, so stopping on the weaker
one guarantees the stronger one is sometimes unmet.

**Stop when the ROPE rule returns either definite answer — decisive *or* practical
tie — or the budget cap is reached.** Both are actionable, which is the property a
stopping rule should have: terminate when there is something useful to say.

This also fixes the opposite failure. On a genuine tie, P hovers near 0.5 and never
crosses, so a P-based rule can *never* stop early on exactly the tests whose answer
was available soonest — it would spend the whole budget establishing a tie the ROPE
could have declared at a fraction of it.

`P >= 0.99` stays as a reported number and keeps the sign-off below. It is no longer
the trigger.

### Reported confidence threshold: P >= 0.99

Signed off 2026-07-27 (not a sourced constant — a product decision, recorded here so
it is not mistaken for one). 0.95 was rejected: [015](015-task-framing-sensitivity.md)
put `P(B>A)` at 1.000000 on a lever that published field data says does nothing to
readers, so a 95% bar buys little protection against a confidently biased panel.
Given how fast P moves, 0.99 costs few extra votes. See the amendment above for why
this threshold is reported rather than used to terminate a run.

### ROPE = ±3 preference-share points — signed off, provenance stated

The band [0.47, 0.53] is an **authored** number: it first appeared in the
2026-07-16 planning grill (`docs/project-idea.md`), was interrogated on 2026-07-27
— including whether it can come from the posterior at all (it cannot: the ROPE
encodes what difference is worth acting on, which is a domain judgment no amount of
data computes) — and was confirmed as the v1 default the same day.

Rules that came with the sign-off:

- **The verdict records the band that produced it.** One field, costs nothing now,
  and it is what keeps every future "change it later" honest instead of silent.
- **`rope_verdict` takes the band as a parameter with ±3 as the default** — the
  same shape as `credible_mass` — so the constant lives in exactly one place.
- **Post-v1, the ROPE becomes user-settable per test** — a real need (different
  domains price a "meaningful difference" differently), deliberately deferred. The
  flow is already decided to prevent verdict-shopping: the band is set when the
  test is *created*, shown in the report, and immutable for that test; re-analysis
  under another band is an explicitly-labeled what-if, never a silent replacement.
  Same principle as project-idea.md's MDE rule: declare before running, not after
  seeing the result. Because the band drives adaptive stopping, a post-hoc band can
  demand data that was never collected — widening after the fact turns "decisive"
  into "undecided" resolvable only by resuming collection.

### The payload names a probability, never a winner

`Verdict.winner` goes. It picks a leader from a raw count with an admittedly arbitrary
tiebreak and no uncertainty at all, and a field called `winner` beside a preference
share is the exact misreading [011](011-build-report-ui.md) is written to prevent. The
response carries `P(B preferred)`, the preference share with its interval, and the
ROPE verdict.

### The posterior is exposed per batch, not only at the end

[011](011-build-report-ui.md) will animate the posterior narrowing as batches arrive.
That is worth more than decoration: a static point estimate invites reading the number
as truth, whereas watching the interval shrink shows uncertainty as something evidence
buys down — the intuition this project most needs its readers to have.

It also costs nothing, since adaptive stopping already computes a posterior per batch.
But it constrains this ticket's API: if the stopping function returns only a decision
and a final summary, the stream has nothing to animate and it would be retrofitted.
Return the sequence.


Reading guide for all of the above, with worked numbers from the shipped
implementation: [`docs/reading-the-posterior.md`](../docs/reading-the-posterior.md).
[011](011-build-report-ui.md)'s copy should be written from it.
