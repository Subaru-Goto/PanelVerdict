# Reading the posterior

What each number out of the Bayesian layer ([009](../issues/009-build-bayesian-layer.md))
means, which pairs of them are easy to confuse, and the analytical facts worth knowing
before writing copy about them. Written for whoever builds
[011](../issues/011-build-report-ui.md) as much as for whoever finishes 009.

Every figure below is computed from the shipped implementation (`app/verdict.py`),
not quoted from a textbook.

## The four numbers

`p` is the share of the panel that prefers variant **B** over **A**. Which variant is
the reference is pure convention — A's share is `1 - p`.

| field | is | reads as |
|---|---|---|
| `share_preferring_b` | E[p] | *about 62% of the panel prefer B* |
| `probability_majority_prefers_b` | P(p > 0.5) | *we are 97% sure more than half do* |
| `interval` | 95% HDI | *the plausible range for that share* |
| ROPE verdict | HDI vs [0.43, 0.57] | *decisive / practical tie / undecided* |

**The first two are the pair to be careful with.** One is the estimate; the other is
confidence in its direction. They move independently:

| votes | share | P(majority) | 95% HDI |
|---|---|---|---|
| 6 / 10 | 0.583 | 0.726 | [0.318, 0.841] |
| 120 / 200 | 0.599 | 0.998 | [0.531, 0.666] |

Nearly the same share — 0.583 against 0.599 — and 73% versus 99.8% confidence. A
report that swaps these two says something false, which is why the field is named
`probability_majority_prefers_b` rather than anything shorter.

## Why the share is not k/n

Six of ten votes is 0.600 raw but `share_preferring_b` reports **0.583**. Two facts
explain it, and neither is a bug.

**0.600 is the posterior *mode*.** For `Beta(1+k, 1+n-k)` the mode is exactly `k/n`,
at every n. The raw proportion has not gone anywhere; it is a different summary of
the same distribution.

**The mean sits below the mode because the posterior is skewed.** `Beta(7,5)` has
skew −0.17. It is skewed because `p` is trapped in [0, 1]: with the peak at 0.6 there
is more room below than above, so the lower tail stretches and drags the mean down.

It is *not* about spread. `Beta(6,6)` — a 5–5 split — has almost the same standard
deviation (0.1387 against 0.1367) and its mean and mode are both exactly 0.5. Width
cannot be the cause of a shift.

Mechanically, `E[p] = (1+k)/(2+n)` — literally *add one vote to each side before
counting*. That is Laplace's rule of succession, and the flat prior's only opinion:
it says nothing about where `p` is, but it refuses to let ten votes speak as loudly
as a thousand.

**The gap closes like 1/n.** For a 60/40 split it is exactly `-0.2/(n+2)`:

| votes | k/n | mode | mean | gap |
|---|---|---|---|---|
| 6 / 10 | 0.6000 | 0.6000 | 0.5833 | −0.0167 |
| 30 / 50 | 0.6000 | 0.6000 | 0.5962 | −0.0038 |
| 120 / 200 | 0.6000 | 0.6000 | 0.5990 | −0.0010 |
| 600 / 1000 | 0.6000 | 0.6000 | 0.5998 | −0.0002 |

So at a full 200-persona panel the shrinkage is a tenth of a point and invisible. At
the small n adaptive stopping can hand you, it is not — which is the reason not to
report `k/n` because it looks tidier.

## Why the interval is an HDI

A 95% credible interval is *any* interval holding 95% of the posterior; there are
infinitely many. Two conventions matter.

- **Equal-tailed** — chop 2.5% from each end.
- **Highest density (HDI)** — the shortest such interval, equivalently the one where
  no point outside is more plausible than a point inside.

For a symmetric posterior they coincide. On a skewed one, the equal-tailed interval
can **include a value less plausible than one it excludes**, because it balances tail
*probability* rather than density:

| posterior | equal-tailed | HDI |
|---|---|---|
| `Beta(9,3)` — 8 of 10 | [0.482, **0.940**] | [**0.516**, 0.959] |
| `Beta(121,81)` — 120 of 200 | [0.5307, 0.6654] | [0.5314, 0.6661] |

In the first row the two give **opposite answers** to "does the interval exclude a
tie?" — equal-tailed dips below 0.5, the HDI does not. In the second they agree to
three decimals.

So the choice only bites at small n or extreme splits, which is exactly where early
stopping may leave a run. That is why the HDI is not optional here.

Two consequences at the edges, both real rather than hypothetical: a **unanimous**
panel leaves the density monotone, so the shortest interval runs to the boundary
(`10/10` gives [0.762, 1.000]) rather than sitting inside it; and an **empty** panel
returns the prior, [0.025, 0.975], which is the honest answer before anyone has voted.

## The ROPE, and the third answer

The **region of practical equivalence** is [0.43, 0.57] — a preference share within
**seven** points of even is treated as not worth acting on. Compare the HDI to it:

| relationship | verdict |
|---|---|
| HDI entirely **outside** the ROPE | **decisive** — credibly different by more than a negligible margin |
| HDI entirely **inside** the ROPE | **practical tie** — credibly *not* different enough to matter |
| HDI **straddles** a ROPE edge | **undecided** — not enough data |

**This third answer is the strongest argument for the Bayesian formulation.** A
classical test can only reject or fail to reject, and "not significant" versus "no
real difference" are entirely different claims a p-value cannot distinguish. The ROPE
returns the second one *positively*.

That is the difference between useless and actionable. "No significant difference"
tells a marketer nothing. "These two are a practical tie — pick either, or test a
bolder variant" tells them what to do next.

### Why ±7 and not ±3

Because a tie has to be *expressible*. For the HDI to sit inside the band it must be
narrower than the band, and at an affordable panel size it is not:

| n | HDI width at an even split | tie at ±3? | tie at ±7? |
|---|---|---|---|
| 150 | 15.8 pts | no | no |
| **200** | **13.7 pts** | no | **yes** |
| 800 | 6.9 pts | no | yes |
| 1,100 | 5.9 pts | yes | yes |

At ±3 the `practical_tie` verdict is unreachable until roughly **1,100 votes**, so the
whole third answer would have been dead on arrival and every genuine tie would have
reported `undecided`. ±7 is the narrowest band that works at n = 200; the exact
requirement is ±6.9.

It is also defensible on its own terms: identical prompts flip 11–20% of the time
([015](research/task-framing.md)), so a 7-point gap sits inside the instrument's own
wobble. And a wider band makes `decisive` **harder** — 64% of votes required rather
than 60% at n = 200 — which is protective against exactly the overclaiming 015 found.

**The band cannot be derived from the posterior**, and this is worth being firm about.
It encodes what difference is worth acting on, which is a domain judgment. No amount
of data computes it: with enough votes the HDI shrinks toward a point, so without a
ROPE every test eventually reads "decisive", including on differences nobody would
notice. The band is what stops *statistically detectable* being read as *worth acting
on*.

For the same reason it must not follow the sample size. The coherent dynamic form is
the reverse — **declare the margin, then size the panel to resolve it** — which is the
power calculation this project already commits to. The table above is that function
read backwards: ±7 wants n≈200, ±5.6 wants n≈300.

**Boundary sensitivity is worth respecting.** At n = 200, 128 votes for B is decisive
and 127 is undecided. One vote. Do not let "decisive" imply robustness in the copy.

## Why adaptive stopping is off by default

Two independent reasons, both measured.

**A P-threshold is the wrong trigger.** `P(p > 0.5) >= 0.99` disagrees with the
verdict at every panel size below ~1,600:

| n | first k reaching P >= 0.99 | P | HDI | verdict |
|---|---|---|---|---|
| 200 | 117 | 0.9919 | [0.516, 0.652] | undecided |
| 400 | 224 | 0.9918 | [0.511, 0.608] | undecided |
| 800 | 433 | 0.9902 | [0.507, 0.576] | undecided |

The two rules ask different questions: `P` asks whether B is ahead **at all**, the
HDI-against-ROPE asks whether B is ahead **by enough to matter**. The second is
strictly stronger, so stopping on the weaker one stops before there is an answer.

**Stopping on the verdict has a worse problem: peeking.** The verdict wobbles as
batches arrive — the HDI narrows but its position also drifts — so every extra look is
another chance to cross a ROPE edge by luck. Simulated over 600 panels, batches of 20
to a cap of 200:

| rule | false `decisive` at a true tie | catches a real 60/40 | avg votes |
|---|---|---|---|
| first definite verdict | ~8–10% | 63.8% | 90 |
| 2 in a row | 3.2% | 48.7% | 113 |
| 3 in a row | 1.2% | 45.3% | 126 |
| **fixed n = 200** | **0.3%** | 52.8% | 200 |

Peeking inflates false `decisive` on genuinely tied variants roughly **25-fold**.

Be precise about what is broken: **not** Bayesian inference. The posterior given the
votes collected is valid however the run stopped — that is the likelihood principle,
and a genuine advantage over p-values. What breaks is the *decision rule* laid on top.
"Stop at the first crossing" is a selection procedure, and it selects for favourable
wobbles.

Confirmation streaks repair most of it but cost detection power: three-in-a-row
catches *fewer* real differences than the full panel, 45% against 53%, because a run
can be decisive at n = 200 without having been decisive at 160 and 180.

**And the trade is not worth making, because the feature exists to save money.** At
$0.0022/vote a full 200-panel costs **$0.44**; stopping early saves about **$0.20 per
test**. Twenty cents against a 25-fold false-positive inflation is a bad deal at any
budget, and an indefensible one for a product whose pitch is not overclaiming.

So **fixed n = 200 is the default**. The machinery still exists and still emits the
per-batch posterior sequence — the animation needs it, and stopping earns its place at
the ~1,100-vote panels tie detection wants, where it saves dollars rather than cents.
It ships disabled.

## The expected preference shortfall, and why it is not called a loss

`expected_preference_shortfall` is the average number of preference-share points a
choice falls short of an even split by, **weighted by the probability that it does**.
Both directions are reported.

It is Bayesian decision theory's *expected loss*, deliberately renamed. In a marketing
report "loss" reads as money, and this measures neither money nor reader behaviour —
only how the panel split. The same rule that forbids calling the share a "lift".

**It decomposes, and the two factors are worth seeing apart:**

```
shortfall  =  P(that choice is worse)  x  average shortfall in that branch
```

| votes | P(majority) | shortfall | = P(B worse) | x avg shortfall |
|---|---|---|---|---|
| 8 / 10 | 0.967 | **0.0019** | 0.0327 | 0.0578 |
| 60 / 100 | 0.977 | **0.0004** | 0.0230 | 0.0186 |
| 30 / 50 | 0.920 | 0.0025 | 0.0804 | 0.0315 |

Read the first two rows together. Confidence is near-identical — 96.7% against 97.7% —
and the shortfall differs **4.4-fold**. Not because the chance of being wrong differs
much, but because being wrong costs three times as much: 5.8 points against 1.9.

**That is the whole reason this number exists beside `probability_majority_prefers_b`.**
Probability tells you *how often* a choice would be wrong. The shortfall tells you *how
far* wrong, weighted by that likelihood. A small panel has fat tails — if it is wrong,
it is wrong by more — and probability alone is blind to that.

Which is also why it is the sounder stopping signal: early stopping lands precisely in
the small-panel regime, where probability looks reassuring and exposure is largest.

**The conditional magnitude is not reported**, only derivable as
`shortfall / P(that choice is worse)`. On its own it carries no likelihood, so it
compares to nothing — 5.8 points sounds alarming until you notice it is 3% likely.

**Copy states the unit every time.** *"If B is the weaker headline, the panel's
preference falls short of even by 0.2 points on average — and there's a 3% chance it
is."* Probability, magnitude and scale in one breath.

Worked end to end for 8 of 10 votes: 96.7% of the posterior says a majority prefers B;
the remaining 3.3% says it does not, and in that branch the true share averages 0.442,
so B trails by 5.8 points; `0.033 x 0.058 = 0.0019`.

With no votes at all the prior gives 1/8 either way — a quarter of the whole scale,
which is what knowing nothing costs.

## What none of these numbers mean

**Not a click-through rate.** `E[p] - 0.5` is in preference-share points. Real readers
mostly see one variant and never make the comparison the panel was asked to make, so a
70/30 forced preference can sit on top of a tiny click difference.

**Not validated on same-meaning variants.** [015](../issues/015-task-framing-sensitivity.md)
found the panel produces confident preferences uncorrelated with published field
effects when the two variants say the same thing differently — which is the regime real
A/B tests live in. On the published *null* it reported `P(majority prefers B) =
1.000000` with a 95% HDI of [0.831, 0.949].

That is the limit of everything above: **the interval quantifies uncertainty about the
panel, not about readers.** Bayesian updating propagates noise correctly and cannot
see bias. More votes narrow the interval around the same value, right or wrong. And
the noise floor fails in the worst direction — a consistently biased panel rarely
flips, so it looks like the most reliable case in the file.
