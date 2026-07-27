# Lessons so far

Two things that were scattered and are now in one place: **what we know about the
panel's behaviour**, synthesised across experiments rather than trapped inside each
one, and **which measurement mistakes we made**, so the next experiment doesn't
repeat them.

Deliberately not duplicated here:

- [`reading-the-posterior.md`](reading-the-posterior.md) — what each reported number
  means, and the copy rules. Read that before writing report UI.
- [`research/manipulation-check.md`](research/manipulation-check.md) — 014 in full.
- [`research/task-framing.md`](research/task-framing.md) — 015 in full.

**Everything below is `openai/gpt-5-mini` at default temperature, measured in July
2026.** None of it transfers to another panel model without re-running, and the model
is config rather than a constant precisely so that stays possible.

---

# Part 1 — What we know about the panel

## It enacts traits, not just reports them

Adding temperament to the prompt changes **32.5%** of votes against a same-prompt
flip rate of **9.9–13.3%**, so roughly 20 points of that is real signal. Openness,
conscientiousness and extraversion each carry a headline pair from 0.00 to 1.00
across the trait's range, monotonically.

This is the specific failure Han et al. 2025 documented — persona injection moving
*self-reported* traits (β=3.95, p<.001) while leaving *behaviour* untouched (β=0.03,
p=.67) — and for this model on this task it does not occur. That is why the flagship
benchmark comparison was dropped: fidelity is established, only relative fidelity
would need it.

## Its instability is the measurement scale, and it is not a constant

Run an identical prompt twice and it disagrees with itself. That rate is the floor
every effect is read against, and **it depends on the stimulus**:

| stimulus regime | same-prompt flip rate |
|---|---|
| Opposed propositions (014) | 0.099–0.133 |
| Same-meaning rephrasings (015) | 0.192–0.236 |

Same model, same personas, same temperature — **twice as unstable** when the two
options mean the same thing. Any effect measured on same-meaning copy has to clear
about 21%, not about 11%.

## It reads the options reliably

The comprehension control ("Free delivery" against "a $14.99 handling fee") returns
**1.00 in every arm and every framing** across both experiments. Whatever else goes
wrong, the model is not answering at random.

## Position bias is large, and its size is diagnostic

It picks whichever option came first **0.66** of the time overall (014), and the bias
concentrates in cells where content preference is weak — where it has a real
preference, order stops mattering.

Which makes position bias a *readout*, not just a nuisance. In 015 it **fell to
0.56** on same-meaning pairs, against the prediction that the weakest-content regime
would push it up. The coherent reading: the model was not falling back on
arrangement, because it had strong preferences on those pairs. They were simply
preferences that do not track people. Low position bias plus wrong answers is a worse
diagnosis than high position bias.

## On same-meaning copy it is confidently wrong

The finding that most constrains the product. Against Gligorić et al. 2023 — twelve
pre-registered hypotheses on 24,333 real Upworthy A/B pairs:

- On the **published null** (second-person pronouns, which do *not* move real
  clicks), the panel prefers the "you" variant **0.82 / 0.90 / 0.94** across the
  three framings. Mean distance from no-preference: **0.387**.
- On the three levers that *do* move real clicks, it lands in the predicted direction
  in **3 of 9** cells, against 4.5 by coin flip.

Magnitudes of 0.04 and 0.99 mean this is not indecision. It is confident, and it
reverses depending on which question is asked. **The panel is unvalidated on
same-meaning variants — which is the regime real A/B tests live in.**

## Framing moves votes but not verdicts

Rewording the question flips **38–43%** of matched votes, against a floor of ~0.21.
Yet the `openness` gradient is *identical* under all three framings — same span, same
significance, monotone in each.

So the wording of the question bites only where the two variants are close in
meaning. On strongly opposed content the verdict is robust to it.

## A saturated pair measures nothing

The neuroticism pair has a no-persona baseline of **1.00** — every persona picks
"Protect what matters" regardless of trait level. Its 0.33 span is a ceiling effect,
not a negative result, and it is uninterpretable either way. Four of 014's six pairs
have baselines above 0.85 or below 0.10.

**Check a pair's no-persona baseline before spending on it.** A pair that everyone
agrees on cannot show that anything moved.

---

# Part 2 — Lessons in measuring it

## Experimental design

**Counterbalancing must not correlate with the treatment.** `collect_panel_votes`
alternates presentation order on panel index, and a five-level sweep is odd — so it
would have shown three personas one order and two the other, with the imbalance
locked to trait level, since VERY_LOW is always index 0. A position-biased model
would then have *manufactured* a gradient shaped exactly like the effect under test.
Caught by writing the test first, before any money was spent. The fix was to run both
orders for every persona in every cell, which also made position bias measurable in
its own right.

**A published null beats a hand-built control.** 014's controls were authored, so a
clean result only showed internal coherence. 015's negative control is a lever that
*published field data says does nothing* — and it fired, producing the single most
informative number in that run for a sixth of its cost. Prefer controls someone else
has already validated.

**The stimulus regime decides what a run can find.** 014's pairs are opposed
propositions, which was correct for "does a trait move a vote" and useless for
anything about wording. Testing framing on them would have measured framing
sensitivity in the regime where it is smallest and returned a comfortable null. Ask
what regime the *product* operates in before choosing stimuli.

**Ablate one thing.** Collapsing trait levels through the same phrase table isolates
granularity; rewording the table would have ablated wording and granularity together.
Same discipline made the vote question a parameter separate from the answer
instruction, so a framing arm structurally *cannot* reword the instruction.

## Analysis

**A cell key that is too coarse pools distinct things silently — and this bit twice.**
`_CELL` defines "the same prompt, run twice". Omitting `framing` from it would have
grouped replicates of *different questions* as identical re-runs: the noise floor
absorbs the entire framing effect, every flip rate then sits at that inflated floor,
and the run reports "framings are interchangeable" whatever the model did. The same
defect, in the same shape, lurked in a test's uniqueness assertion. Neither raises.
**When you add a dimension, find every key that should now include it.**

**A biased model has a *low* noise floor, so the reliability statistic fails in the
worst direction.** A model that answers the same way every time looks stable. The
`second_person` cell — the panel's most wrong result — is among its most *consistent*,
so the floor makes it look like the most trustworthy cell in the file. No internal
statistic catches bias. Only external validation does.

**Make impossible cases loud, not zero.** A category with a target proportion of 0
admits no sampling error, so a naive z-score renders the most damning sampler bug as
`z = 0.00` — a perfect score. It is `math.inf`. The general rule: when a denominator
vanishes, ask what the *worst* interpretation would look like on the report.

**Aggregate identity hides total disagreement.** Two arms can report the same margin
with every vote flipped, which is why flip rates are computed on *matched* votes
rather than as a difference of shares.

**Exclude a control from statistics it would distort.** The comprehension pair is
authored so nobody disputes it, so pooling it into the noise floor pins a sixth of
that statistic near zero. But the *published null* pair stays in — the model has a
genuine choice there. "It's a control" is not by itself a reason to exclude.

## Statistics

**Bayesian updating propagates noise and cannot see bias.** On the published null the
layer reports `P(majority prefers B) = 1.000000` with a 95% HDI of [0.831, 0.949].
Nothing malfunctioned. The credible interval quantifies uncertainty about *the
panel's* preference share; whether that share tracks readers is a different question
and not a sampling one. **More votes narrow the interval around the same wrong
value.**

**Some numbers cannot come from the data, and pretending otherwise is the error.**
The ROPE encodes what difference is worth acting on — a domain judgment. With enough
votes the interval shrinks toward a point, so *without* a band every test eventually
reads "decisive", including on differences nobody would notice. And the band must not
follow the sample size, or the instrument defines the business threshold. The
coherent dynamic form is the reverse: declare the margin, then size the panel.

**A verdict needs a band it can express.** ±3 points looked reasonable and was
unreachable: the interval is 13.7 points wide at n=200 and does not fit inside a
6-point band until ~1,100 votes. The `practical_tie` verdict — the thing that
justifies the whole method — was dead on arrival. **Check that a threshold is
achievable at the sample size you can afford.**

**Peeking breaks the decision, not the inference.** Stopping at the first definite
verdict inflates false `decisive` on a genuinely tied panel from 0.3% to ~8–10%. The
posterior given the collected votes is valid however you stopped — that is the
likelihood principle. What breaks is the rule laid on top: stop-at-first-crossing
*selects* for favourable wobbles. Confirmation streaks repair most of it and cost
detection power.

**A test oracle must reach the answer by a different route.** `P(p > 0.5)` is verified
against a finite binomial sum, available because integer counts under a flat prior
keep both Beta parameters integer — arithmetic the implementation never performs. An
oracle that restates the implementation's own formula passes by construction.

## Process

**Measure, don't estimate — and in the unit that actually runs out.** Two failures of
the same kind. I said "~5 hours" for a sweep from a guess; measuring file timestamps
gave 4.65 s/vote and ~7 hours. Then I sized 015 entirely in *wall-clock minutes* and
never in dollars, on a project with a hard budget — a run cost ~$4 against $10
remaining. Wall-clock is not the cost that runs out.

**Price a feature before optimising it.** Adaptive stopping saves ~$0.20 per test and
inflates false `decisive` 25-fold. I spent a long time reasoning about the stopping
*rule* without once asking what stopping *buys*. The trade was never close.

**When a test fails, the test may be wrong.** It happened twice on one branch — the
uniform prior integrates to 1/8 not 1/16, and a wide band does not make a small batch
a tie. Both times the code was right. Verify independently before deciding which side
to change.

**A number that looks plausible is not a number.** While replacing equal-tailed
intervals with HDIs I *typed* one bound instead of computing it — off by two
thousandths, in a spec someone could later cite. Small, and exactly the habit the
no-unsourced-constants rule exists to catch.

**Check the whole blast radius, not the language you were editing.** Renaming an API
field, I grepped Python, declared the impact small, and left the frontend reading a
deleted field. The security review found it as an aside.

---

## What none of this covers

Whether the panel predicts **real human behaviour**. Everything above is internal
coherence plus two published comparisons on four sentence pairs. The real test is the
Upworthy archive — ~32,000 real A/B tests with impressions and clicks — and it is out
of scope on the map. Until then the honest claim is that the panel responds
consistently to its own inputs, and on same-meaning copy we have direct evidence that
consistency is not accuracy.
