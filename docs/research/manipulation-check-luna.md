# Manipulation check on gpt-5.6-luna — the 071 gate result

**Run 2026-08-23.** `openai/gpt-5.6-luna` via OpenRouter, default temperature, default
reasoning. **5,400 votes** — the exact 014 design (5 traits × 5 levels × 6 pairs × 3 arms
× 6 replicates × 2 orders, `preference` framing only), so every row is comparable to the
recorded gpt-5-mini run of 2026-07-26. Ticket:
[071 · #162](https://github.com/Subaru-Goto/PanelVerdict/issues/162). Raw rows are a
re-runnable artifact, not committed; regenerate with

```
uv run python -m experiments.manipulation_check --replicates 6 \
    --pairs openness,conscientiousness,extraversion,agreeableness,neuroticism,control \
    --framings preference --workers 8 --out experiments/out/votes-luna.jsonl
uv run python -m experiments.analysis experiments/out/votes-luna.jsonl
```

## Verdict: the gate is passed — Luna enacts, `-pro` was not needed

Persona traits steer votes far beyond the model's own noise, with clean controls. Per
plan B in [panel-model-selection.md](panel-model-selection.md), a pass on the cheapest
variant ends the search: **`openai/gpt-5.6-luna` is confirmed as the panel model**, and
`-pro` stays untested because nothing required it — recorded as a finding, not an
omission.

| measure | gpt-5-mini (2026-07-26) | gpt-5.6-luna (2026-08-23) |
|---|---|---|
| flip rate, trait-free → trait arm | 32.5% | 23.6–23.7% |
| noise floor (same prompt re-run) | 9.9–13.3% | 9.1–13.1% |
| excess over floor | ~20 pts | ~10–14 pts |
| never→always traits (span 1.00, monotone) | openness, conscientiousness, extraversion | **same three** (z = 4.90 each, traits_5) |
| agreeableness | weaker but ordered | same shape: 0 → 0.33, z = 2.19, monotone |
| neuroticism | **untestable** (pair saturated at 1.00) | measurable: span 0.42, z = 2.51, non-monotone dip at `medium` |
| control (comprehension) pair | ~1.00 everywhere | 1.00 in every arm |
| trait-free arm gradients | flat | flat (\|span\| ≤ 0.25, \|z\| ≤ 1.26) |
| 3-level vs 5-level rendering | no detectable difference | flip 9.3% ≈ floor — same |
| first-position rate | 0.66 | 0.62 |

**Read honestly: enactment is confirmed and somewhat smaller.** The headline flip rate
dropped ~9 points against a floor that stayed put. The gradient structure — which traits
carry, in what order, how strongly at the extremes — reproduced almost exactly, so what
shrank is the mid-level responsiveness, not the mechanism. Two genuine improvements ride
along: the neuroticism pair is measurable for the first time (its baseline came off the
1.00 ceiling), and position bias eased 0.66 → 0.62 (002's counterbalancing still earns
its place either way).

## The reasoning finding: enactment survives near-zero reasoning

The cost probe (below) measured **~6.5 reasoning tokens per vote** on Luna against
gpt-5-mini's ~160 (68% of its bill, [vote-usage instrumentation](../decisions/010a-vote-usage-instrumentation.md)).
The gate shows trait enactment does not depend on that reasoning budget — which also
means escalating to `-pro` (same model, `reasoning.mode=pro`) would have changed *what
the panel is* (071's own warning) to buy something the data says was not missing.

## Cost: measured, and the estimate falls

From the 20-vote `vote_cost` probe (2026-08-23, provider-reported `cost` field — the
method [010a](../decisions/010a-vote-usage-instrumentation.md) validated bit-for-bit
against list-price derivation):

- **$0.0001212/vote** reported (10/10 default-arm votes) → **$0.0242 per 200-vote test**
- against gpt-5-mini's measured $0.107/200: **~77% cheaper** — the author's ">50%
  cheaper" expectation (2026-08-23), confirmed and exceeded
- the full 5,400-vote gate derives to ≈ **$0.65**, consistent with the spend observed on
  the account dashboard during the run
- prompt sizes in the probe (~352 tokens) sit inside the prod vote's measured 270–370
  range, so the per-vote figure transfers
- harness nit, recorded: `vote_cost`'s "cost derived" line still prices at gpt-5-mini's
  $0.25/$2.00 — the *reported* column is the authoritative one

`USD_PER_VOTE` in `config.py` moves from the 0.0003 estimate to a measured-with-margin
0.00015 (derivation at the constant).

## What this run does NOT cover

- **015's framing sensitivity and negative control are still gpt-5-mini results.** The
  published validity caveat (unvalidated on same-meaning copy) rests on them, and they
  are unmeasured on Luna. This run gates *enactment*, not *validity* — the README caveat
  stands unchanged.
- The extra pairs and framings added to the harness since 014 (`pronoun_person`,
  `person_number`, `article`, `second_person`; `click`, `attention`) were deliberately
  excluded to keep the comparison clean; re-running 015's slice on Luna is its own
  decision.
