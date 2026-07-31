# The targeting call: reasoning effort, output cap, and the runaway

Measured 2026-07-31, on `openai/gpt-5-mini` via OpenRouter, Chat Completions with
structured output (`with_structured_output(TargetRequest, include_raw=True)`).

This exists because a single translation call cost **$0.13** — roughly a whole
200-vote panel run — by generating 65,536 completion tokens and then failing to
parse. It sources two constants in `app/llm.py`: `TARGET_MAX_COMPLETION_TOKENS`
and `TARGET_REASONING_EFFORT`.

## How it was found

The targeting call had **no read timeout and no output cap**, so it inherited the
SDK's defaults. A bare translation ran past ten minutes and was killed. The
timeout was fixed first — but a timeout bounds an *idle* connection, and a model
streaming 65k tokens is not idle. The failure that actually cost money was
runaway generation, which only an output cap bounds.

## Reasoning is most of the bill

Default effort, one call per description, `max_tokens=4096`:

| description | output | of which reasoning | JSON | cost |
|---|---|---|---|---|
| `anyone` | 157 | 64 | ~93 | $0.00036 |
| `japanese people in their 40s` | 769 | 640 | ~129 | $0.00159 |
| `retirees in germany` | 627 | 512 | ~115 | $0.00131 |
| `cautious young german homeowners who play golf` | 1275 | 1088 | ~187 | $0.00260 |
| `young japanese people` | **hit the 4096 cap and failed** | — | — | ≥$0.008 |

Reasoning is **40–85%** of every response, and the structured output itself never
exceeds ~190 tokens. The task is extraction against a typed schema, so nearly all
of the spend buys deliberation about a JSON shape.

**The runaway is stochastic, not input-specific.** `young japanese people`
succeeded twice earlier in the same session (18–29 and 18–30) and then blew the
4096 cap on the third attempt. No description is safe by inspection, which is why
the cap is a bound on blast radius rather than a fix.

## `none` is impossible on this endpoint

```
400: Reasoning is mandatory for this endpoint and cannot be disabled.
```

Recorded because it looks like the obvious lever and is not available. The repo's
`ReasoningEffort` vocabulary lists `none`, and the provider accepts the parameter
name — it rejects the *value* for this endpoint. Distinct from the trap in
[010a](../../issues/010a-vote-usage-instrumentation.md), where an **unrecognised**
effort is accepted and silently does nothing: this one fails loudly.

## `minimal` is cheapest and wrong

| description | output | reasoning | parsed |
|---|---|---|---|
| `anyone` | 61 | 0 | — |
| `japanese people in their 40s` | 111 | 0 | age 40–49 |
| `young japanese people` | 80 | 0 | **`unmapped=['japanese people']`** |
| `retirees in germany` | 80 | 0 | `unmapped=['retirees']` |
| `cautious young german homeowners…` | 157 | 0 | `cautious` → **neuroticism** |

Reasoning drops to **0 on every call** and the five calls cost $0.0015 — but
`young japanese people` **loses the country**, putting "japanese people" in
`unmapped` instead of Japan in `regions`. That violates prompt rule 1 and would
silently draw a panel from the whole pool. Rejected on accuracy, not cost.

It also read "cautious" as neuroticism where every other arm says
conscientiousness — one of the judgement calls
[016](../../issues/016-translation-accuracy-golden-set.md) already flags as having
no ground truth, so not wrong, but a change.

## `low` — adopted

| description | output | reasoning | cost | parsed |
|---|---|---|---|---|
| `anyone` | 136 | 64 | $0.00061 | — |
| `japanese people in their 40s` | 310 | 192 | $0.00067 | age 40–49, no phrase |
| `young japanese people` | 387 | 256 | $0.00082 | age 18–30, phrase `young` |
| `retirees in germany` | 437 | 320 | $0.00093 | **age 65–100, phrase `retirees`** |
| `cautious young german homeowners…` | 531 | 384 | $0.00111 | age 18–34, `cautious` → conscientiousness |

Reasoning falls ~3× against default, cost lands in a tight $0.0006–0.0011 band,
and accuracy holds — *including* the two cases `minimal` got wrong. It also does
something the default arm did **not**: `retirees` produced an age span rather than
landing in `unmapped`, so [024](../../issues/024-fuzzy-age-words-in-targeting.md)'s
rule 4 fires on a word the default arm dropped.

Adoption is cheap here in a way it is not for votes.
[010a](../../issues/010a-vote-usage-instrumentation.md) declined `low` on the vote
path because 014's position-bias rate and 015's framing sensitivity were both
measured at default effort. The translator has no measurement pinned to default
effort, and it has no fingerprint, so no cached work is invalidated.

## `TARGET_MAX_COMPLETION_TOKENS = 4096`

Derived, not chosen: **~3× the largest legitimate response observed** (1,275
tokens, the four-attribute description at default effort). It must comfortably
exceed real work, since hitting it turns a valid translation into a failure.

Two things it buys, both observed rather than argued: it **caught a real runaway**
in this measurement — `young japanese people` failed at the cap instead of
reaching 65,536 — and it bounds the worst case at roughly **$0.008 instead of
$0.13**, a ~16× reduction.

Kept independent of the effort change on purpose. Five samples cannot show that
`low` prevents runaways; the cap is what makes the tail affordable either way.

## What this does not establish

- **n = 1 per cell.** Single samples per description per arm, chosen to span easy,
  explicit, fuzzy and multi-attribute inputs. Enough to reject `minimal` on a
  clear failure and to size a cap; not enough to compare `low` against default on
  accuracy. That is [016](../../issues/016-translation-accuracy-golden-set.md)'s
  golden set, still unbuilt.
- **Whether `low` runs away.** Not observed in five calls. Not disproven either.
- **The judge and the embedder.** Both now have timeouts but **no output cap**, and
  the judge is a structured-output chat call with the same exposure. Its
  legitimate output size is unmeasured, so capping it without measuring risks
  truncating valid work.

## Prompt caching fires here

Every call above reports `prompt_tokens` ≈ 1,355–1,362 with `cached_tokens` ≈
1,280. The target prompt clears the 1,024-token minimum that the **vote** prompt
cannot — see [prompt-caching.md](prompt-caching.md), whose conclusion is scoped to
the vote path.
