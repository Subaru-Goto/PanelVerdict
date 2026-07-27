# Task-framing sensitivity, and a failed validity check

**[015](../../issues/015-task-framing-sensitivity.md) · 2026-07-27 · `openai/gpt-5-mini`**

Does the panel's verdict depend on how we word the question? And, since the
stimulus set had to be rebuilt to ask that honestly, does the panel reproduce
copy effects that are known to move real readers?

The first question got a split answer. The second got a clear no.

## Method

[014](manipulation-check.md)'s harness, sweeping the **task** half of the prompt
instead of the persona half. Three questions, one sentence apart:

| id | question |
|---|---|
| `preference` | *Which do you prefer?* — what production ships |
| `click` | *Which would you be more likely to click?* |
| `attention` | *Which one catches your eye?* |

Only that sentence varies. The positional and content-based-reason instructions
sit in a separate constant the framing parameter cannot reach, so this ablates
framing without also ablating instruction-following.

**The stimulus set was rebuilt for this run.** 014's six pairs are semantically
opposed propositions — different offers. Real A/B tests hold the meaning and
change the wording, which is also the regime 014 showed to be *hardest* for the
model: position bias concentrates where content preference is weak. Testing
framing only on opposed pairs would have measured it where it should be smallest.

So four pairs are one proposition worded two ways, each moving a single lever
whose direction comes from Gligorić et al. 2023 — twelve pre-registered
hypotheses tested on 24,333 real Upworthy A/B pairs:

| id | lever | predicted | published |
|---|---|---|---|
| `pronoun_person` | 1st singular vs. plural | singular | β +0.241 vs. −0.149 |
| `person_number` | 3rd singular vs. plural | singular | β +0.216 vs. +0.094 |
| `article` | indefinite vs. definite | indefinite | β +0.125 vs. +0.033 n.s. |
| `second_person` | "you" present vs. absent | **no difference** | β +0.051, rejected |
| `control` | *(from 014)* | obvious option | comprehension |
| `openness` | *(from 014)* | trait-conditional | discrimination |

`second_person` is a **published negative control**: a lever real clicks do not
respond to. `openness` is kept because a flat result would otherwise be ambiguous
— framings agree, or there was no signal to disagree about.

1,800 votes — 3 framings × 25 sweep personas × 6 pairs × 2 replicates × both
presentation orders — in the `traits_5` arm. 20m44s at 8 workers, 0.69 s/vote.

## Headline

**The verdict is framing-dependent at the vote level and framing-stable at the
verdict level.** Framing flips 38–43% of matched votes against a noise floor of
0.19–0.24, yet the `openness` gradient is identical under all three framings.

**And the panel fails its published negative control, hard.** The lever that does
nothing to real clicks produces the largest, most consistent preference in the
run; the three levers that do move real clicks land at chance.

## Validity checks

| check | result | reading |
|---|---|---|
| Comprehension (`control`) | 1.00 / 1.00 / 1.00 | The model reads the options under every framing. The gate passes. |
| Noise floor | 0.236 / 0.192 / 0.200 | Roughly double 014's 0.099–0.133. |
| Position bias | 0.56 / 0.55 / 0.57 | Lower than 014's 0.66. |

The floor is the one to notice. Same model, same personas, same temperature — the
only change is that four of six pairs now mean the same thing. Identical prompts
flip about twice as often in that regime. Every effect below is read against
~0.21, not against 014's ~0.11.

## Findings

### 1. The published null is the strongest effect in the run

| framing | share | z | n |
|---|---|---|---|
| preference | 0.82 | 6.4 | 100 |
| click | 0.90 | 8.0 | 100 |
| attention | 0.94 | 8.8 | 100 |

Mean distance from the no-preference point: **0.387**. The panel strongly prefers
*"Three ways **you can** lower a heating bill"* to *"Three ways to lower a heating
bill"*, under every framing, where the field data says the difference does not
move readers.

This is the finding the control existed to produce, and it is more informative
than any of the positive results.

### 2. Agreement with published direction is at chance

Predicted >0.50 in every cell. Observed above 0.50 in **3 of 9**, against 4.5
expected from a coin flip.

| lever | preference | click | attention |
|---|---|---|---|
| `pronoun_person` | 0.04 | 0.42 | 0.19 |
| `person_number` | 0.24 | 0.99 | 0.95 |
| `article` | 0.67 | 0.09 | 0.17 |

The magnitudes matter more than the count. 0.04 and 0.99 are not indecision —
they are strong, confident preferences that reverse depending on which question
is asked.

### 3. Framing moves votes well past the floor

| comparison | matched flip rate |
|---|---|
| preference → click | 0.430 |
| preference → attention | 0.378 |

Against a floor of ~0.21, framing roughly doubles the rate at which a vote
changes. The wording of the question is not cosmetic.

### 4. But the verdict on strongly opposed content does not move

`openness`, share choosing the predicted-high option by trait level:

| framing | very_low | low | medium | high | very_high | span | z |
|---|---|---|---|---|---|---|---|
| preference | 0.00 | 0.00 | 0.50 | 1.00 | 1.00 | 1.00 | 2.83 |
| click | 0.00 | 0.00 | 0.75 | 1.00 | 1.00 | 1.00 | 2.83 |
| attention | 0.00 | 0.00 | 0.50 | 1.00 | 1.00 | 1.00 | 2.83 |

Monotone in all three, same span, same significance. Where the two options
genuinely differ in meaning, the question wording changes nothing.

### 5. Position bias fell, and the reason matters

014 measured 0.66 and found order mattered most where content preference was
weak. The prediction going in was that same-meaning pairs — the weakest-content
regime available — would push position bias *up*. It went down, to 0.56.

The coherent reading is that the model is **not** falling back on arrangement. It
has strong content preferences on these pairs. They are simply preferences that
do not track what moves people.

## Limitations

- **One sentence pair per lever, so "the lever" and "this sentence" are perfectly
  confounded.** `pronoun_person` at 0.04 may be about grocery bills rather than
  about *I* versus *we*. This is the limitation most likely to overturn finding 2,
  and the fix is several pairs per lever.
- **Gligorić's β's are within-experiment associations over naturally-occurring
  headlines, not minimal-pair manipulations.** The pair structure controls for the
  article, but features co-vary. Expecting a constructed minimal pair to reproduce
  the direction is our extrapolation; only directions transfer, never magnitudes,
  and β = 0.241 is not "24% more clicks".
- **The panel is 25 constructed personas, all 42-year-old US women** with one Big
  Five trait swept. The published effects are population-level over Upworthy's real
  audience. This is a thin basis for a population-level comparison, and it is a
  real alternative explanation for finding 2 — though a weak one for finding 1,
  where the effect is near-total.
- **Domain gap.** Upworthy is 2013–15 social news; these pairs are product
  marketing.
- **One model, one temperature, one day.** Nothing transfers to another panel model
  without re-running.
- Replicates are repeated samples from one model, not independent people, so the
  z-scores rank rather than test. No multiple-comparison correction across the 12
  lever cells.
- The three framings are authored. A null across them would have read two ways —
  robust verdict, or three questions too alike to separate. That reading is moot
  here, since they did separate.

## What this settles

- **The question wording is not a free choice, and the reported number depends on
  it** in the same-meaning regime. [009](../../issues/009-build-bayesian-layer.md)
  must name the reported quantity after the question actually asked, and
  [011](../../issues/011-build-report-ui.md) must carry a framing caveat rather
  than presenting one number as *the* verdict.
- **The panel is unvalidated on same-meaning copy, with evidence rather than
  suspicion.** 014 established that traits steer votes between opposed
  propositions. It does not follow that the panel is informative about rephrasing,
  and this run is direct evidence against assuming so. 011 must not present a
  preference share on same-meaning variants as a prediction about readers.
- **`preference` stays as the shipped framing** — not because it won, but because
  nothing here gives grounds to change it. Its agreement with published direction
  is no worse than the others, and switching to `click` on construct grounds would
  imply a predictive claim this run does not support.
- **The negative control is now the most valuable instrument in the harness.** It
  cost a sixth of the run and produced the only unambiguous result.

## What this does not settle

Whether the panel reproduces *any* published copy effect. Finding 2 is at chance
across three levers with one sentence pair each — enough to remove the assumption,
not enough to conclude the panel cannot do it. That needs several pairs per lever
so the sentence and the lever come apart, which is its own experiment and its own
ticket.
