# Targeting manipulation check — result

**Run 2026-07-26.** `openai/gpt-5-mini` via OpenRouter, default temperature. 5,400
votes in 49m 35s. Ticket: [014](../../issues/014-targeting-manipulation-check.md).
Harness: `backend/experiments/`. Raw rows are not committed (they are a
re-runnable artifact, not a source); regenerate with

```
uv run python -m experiments.manipulation_check --replicates 6 --workers 8 \
    --out experiments/out/votes.jsonl
uv run python -m experiments.analysis experiments/out/votes.jsonl
```

## The question

Does a persona attribute steer a vote? Nothing in this project had tested it, and
[001](../../issues/001-decide-persona-schema-and-seed.md),
[003](../../issues/003-decide-panel-model-and-provider.md) and
[006b](../../issues/006b-demographics-sampler.md) each defer a decision to the
answer. `persona-attributes-grounding.md` states the stakes plainly: trait
targeting "remains an unproven **hypothesis**", and the enactment literature is
actively skeptical — Han et al. 2025 found persona injection moved *self-reported*
agreeableness (β=3.95, p<.001) while leaving behaviour untouched (β=0.03, p=.67).

## Method

Five personas identical in every field — 42, female, US, secondary education,
third income quintile — except one Big Five trait, swept across all five rendered
levels. Each votes on six headline pairs, in both presentation orders, six times
each, under three prompt variants:

| arm | persona prompt |
|---|---|
| `demographics` | demographic sentence only, no temperament |
| `traits_3` | temperament rendered with the extremes folded onto their neighbours |
| `traits_5` | temperament as production renders it |

`5 traits × 5 levels × 6 pairs × 3 arms × 6 replicates × 2 orders = 5,400`.

Five pairs are authored to load on one trait each; the sixth is a positive control
("Free delivery on every order" / "A $14.99 handling fee applies to every order")
whose answer no persona should dispute.

## Headline

**Adding temperament to the prompt changes 32.5% of votes.** The same prompt run
twice changes 9.9–13.3% of votes on its own, so roughly 20 points of that is the
manipulation rather than the model's own variability.

## Validity checks, all passing

- **Positive control: 1.00 in all three arms.** The model reads the options.
- **Negative control: flat.** In the `demographics` arm the five sweep personas
  render an *identical* prompt, since the only thing distinguishing them is the
  trait that arm omits — so any gradient there is artifact. Observed spans:
  0.00, 0.00, 0.00, 0.00, 0.17. The measurement does not manufacture effects.
- **No trait moves the control pair.** Zero across the entire 5×6 matrix, which
  rules out "the model just responds to any distinctive persona cue".
- **Position bias measured at 0.66** — the model picks the first-shown option two
  thirds of the time. It cannot contaminate any result here because every persona
  sees both orders, and it concentrates in cells where content preference is weak.
  This is the number [002](../../issues/002-decide-vote-schema.md) asked for.

## Per trait

Share choosing the predicted-high option, `traits_5`, by rendered level:

| trait | very low | low | medium | high | very high | span | monotone |
|---|---|---|---|---|---|---|---|
| openness | 0.00 | 0.00 | 0.42 | 1.00 | 1.00 | **1.00** | yes |
| conscientiousness | 0.00 | 0.00 | 0.58 | 1.00 | 1.00 | **1.00** | yes |
| extraversion | 0.00 | 0.00 | 0.42 | 1.00 | 1.00 | **1.00** | yes |
| agreeableness | 0.00 | 0.00 | 0.25 | 0.42 | 0.67 | 0.67 | yes |
| neuroticism | 0.67 | 1.00 | 0.92 | 1.00 | 1.00 | 0.33 | no |

Three traits move the vote from never to always. The effect is larger than it
looks: the openness and extraversion pairs have no-persona baselines of 0.08 and
0.02, so the trait is *overturning* a strong prior rather than tipping a coin.

## Finding 1 — the neuroticism pair cannot measure neuroticism

Its no-persona baseline is **1.00**. Every persona picks "Protect what matters
before something goes wrong" with no temperament in the prompt at all, so a
high-neuroticism persona has no headroom to move into. The pair can only register
movement downward, and the 0.33 span is entirely low-neuroticism pulling away.

**The neuroticism result is uninterpretable, not negative.** The stimulus is at
fault. Nothing should be concluded about neuroticism until the pair is replaced
with one whose baseline sits nearer 0.5 — which is what the agreeableness pair
(baseline 0.45) does well and what the others do only by luck.

Baselines, `demographics` arm: openness 0.08, conscientiousness 0.87,
extraversion 0.02, agreeableness 0.45, neuroticism 1.00, control 1.00.

## Finding 2 — no detectable difference between three levels and five

Restricted to the extreme levels, where the two renderings actually differ, the
`traits_3` → `traits_5` flip rate is **0.127** against a noise floor of
**0.124–0.133**. The comparison covers 600 matched votes, so an excess of about
**2.7 percentage points** over the floor would have been resolvable. None was
seen.

Read this as *not significant at this power*, not as *no effect*. Smaller
differences remain entirely possible, and the result is conditional on this model,
this temperature, these phrasings and these pairs — a differently worded prompt
could move it. One weak hint in favour of five levels: agreeableness's gradient is
properly ordered at five levels (0.00 / 0.00 / 0.25 / 0.42 / 0.67) and is not at
three (0.00 / 0.00 / 0.17 / 0.58 / 0.42). One trait, at this sample size, is not
evidence.

The consequence for [006j](../../issues/006j-persona-summary-embedding.md) D1b is
narrow. That decision had two justifications; the vote-path one — that two
personas a standard deviation apart were receiving identical voting instructions —
is not visible in behaviour here. The retrieval one, that finer levels give the
summary embedding more to rank on, is untouched by this experiment. Five levels
stay.

## Finding 3 — the traits are separate levers, but the stimuli overlap heavily

Span (very high − very low) per swept trait × pair, `traits_5`. The trait's own
pair is starred:

| swept trait | openness | conscient. | extravers. | agreeable. | neurotic. | control |
|---|---|---|---|---|---|---|
| openness | **1.00\*** | −1.00 | 0.58 | −0.50 | −1.00 | 0.00 |
| conscientiousness | −0.75 | **1.00\*** | −0.42 | −0.33 | 0.83 | 0.00 |
| extraversion | 0.42 | −0.33 | **1.00\*** | 0.67 | −0.50 | 0.00 |
| agreeableness | 0.17 | −0.17 | 0.50 | **0.67\*** | −0.25 | 0.00 |
| neuroticism | −0.58 | 0.50 | −0.33 | −0.25 | **0.33\*** | 0.00 |

For conscientiousness, extraversion and agreeableness the own pair is the largest
effect, so each trait carries something specific. The worst case — one latent axis
wearing five labels — is ruled out.

But the off-diagonals are large and *structured*, not noise. Openness pushes one
way on nearly every pair; conscientiousness and neuroticism push the other. The
five pairs evidently share a strong "novel and spontaneous vs. proven and
cautious" dimension, and much of each trait's measured effect travels along it.

**Consequence for [007](../../issues/007-build-targeting-query-translation.md):**
targeting can select confidently along that broad dimension and only partially
along an individual trait. A target description naming one trait will return a
panel that also differs on the others.

## Limitations

- **This tests internal coherence, not accuracy.** It shows the machine responds
  to its own inputs in a consistent direction. It says nothing about whether the
  panel predicts real humans — `project-idea.md` is explicit that passing is
  "necessary, not sufficient".
- **One model, one temperature, one day.** Nothing here transfers to another panel
  model without re-running it.
- **One base persona.** Demographics were held fixed throughout, so this says
  nothing about whether age, income or education move a vote.
- **One trait at a time.** Real personas carry five levels at once, drawn
  correlated; interactions are untested and could differ.
- **The trait-to-copy mapping is authored, not sourced.** The grounding research
  documents copy levers only for the deferred attributes (NFC → verbal complexity,
  CSII → social proof), not for the Big Five domains.
- **Replicates are repeated samples from one model, not independent people**, so
  the z-scores in the tooling are optimistic and are used for ranking, not as
  p-values. There is no multiple-comparison correction across the 15 gradients.
- **Four of six pairs have baselines above 0.85 or below 0.10**, which compresses
  the range available to any manipulation.
- **All six pairs are semantically opposed propositions, not rephrasings of one
  proposition** — the regime the product actually ships into, where a real A/B test
  holds the meaning and changes the wording. Opposition was the right instrument for
  *this* question, since a trait can only steer a vote on a pair where it predicts a
  direction. But nothing here shows a persona moves a vote between two wordings of the
  same offer, which is the case a customer will bring.
  [015](../../issues/015-task-framing-sensitivity.md) carries pairs in that regime,
  grounded in Gligorić et al. 2023.

## What this settles

- **The gate is passed.** Persona traits steer votes far beyond the model's own
  variability, with the negative controls clean. Work built on the persona pool is
  not built on nothing.
- **[003](../../issues/003-decide-panel-model-and-provider.md)'s fidelity concern
  is answered for `gpt-5-mini`** — it enacts Big Five in behaviour, not merely in
  self-report, which is the specific failure Han et al. documented. The flagship
  benchmark comparison is no longer needed to establish that traits work at all;
  it would only be needed to compare fidelity.
- **[001](../../issues/001-decide-persona-schema-and-seed.md)'s earn-their-place
  gate is now usable.** NFC, maximizing and CSII can be tested with this harness
  by adding a pair and a rendering, at roughly 20 minutes per trait.
