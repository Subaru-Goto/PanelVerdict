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
| ROPE verdict | HDI vs [0.47, 0.53] | *decisive / practical tie / undecided* |

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

The **region of practical equivalence** is [0.47, 0.53] — a preference share within
three points of even is treated as not worth acting on. Compare the HDI to it:

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

**Boundary sensitivity is worth respecting.** 120 of 200 gives an HDI of
[0.531, 0.666] against a ROPE ceiling of 0.530. It is decisive by **one
thousandth** — a single vote either way flips it to undecided. Do not let the word
"decisive" imply robustness in the copy.

## Why stopping on P is the wrong trigger

The natural stopping rule is "stop when `P(p > 0.5)` crosses a threshold". It
disagrees with the verdict rule **systematically at every panel size**:

| n | first k reaching P ≥ 0.99 | P | HDI | verdict |
|---|---|---|---|---|
| 200 | 117 | 0.9919 | [0.516, 0.652] | undecided |
| 400 | 224 | 0.9918 | [0.511, 0.608] | undecided |
| 800 | 433 | 0.9902 | [0.507, 0.576] | undecided |
| 1600 | 847 | 0.9906 | [0.505, 0.554] | undecided |

A run stopping the moment `P ≥ 0.99` therefore stops and then reports
*inconclusive* — the votes are spent, the criterion is met, and there is no answer.

The reason is that the two rules ask different questions:

- `P(p > 0.5) ≥ 0.99` — *are we sure B is ahead at all?*
- HDI against the ROPE — *are we sure B is ahead by enough to matter?*

The second is strictly stronger, so it needs more evidence, so stopping on the weaker
one guarantees the stronger one is sometimes unmet.

**Hence: stop on the verdict.** Terminate when the ROPE rule returns either definite
answer, or the budget cap is reached. A `P`-based rule also has the opposite failure —
on a genuine tie `P` hovers near 0.5 forever, so it can never stop early on exactly
the tests whose answer was available soonest, and would burn the whole budget on them.

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
