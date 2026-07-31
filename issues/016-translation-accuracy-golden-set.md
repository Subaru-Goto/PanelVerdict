---
title: "Translation accuracy: does the target prompt return the right filters?"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Goal

Measure whether [007](007-build-targeting-query-translation.md)'s translator turns a
target description into the **right** `TargetRequest`. Nothing tests this today: the
prompt has a wiring test (every enum value appears in it) and every downstream test
uses `StubTranslator`, so the model's output quality is unmeasured. The only evidence
it works is five live calls that were read once and asserted on never.

Deliverable: a golden set plus a per-field score report, runnable on demand.

## Why not RAGAS

RAGAS grades **generation** over retrieved context — faithfulness, answer relevancy —
and it needs an LLM judge because its target output is prose with no single right
answer. Our translator emits a **typed struct with a known correct value**. Checking
`min_age == 40` needs `assert`, not a judge; adding one would buy cost,
nondeterminism, and a second thing that can be wrong. Judge tooling belongs in
[012](012-build-analyst-chatbot-tools.md), where answers are free text.

## The load-bearing design decision: two classes of assertion

Some of the prompt's rules have a right answer and some do not. Conflating them means
failing the model for disagreeing with a guess of ours.

**Hard requirements — exact match, a miss is a failure:**

| description fragment | expected |
|---|---|
| "in their 40s" | `min_age=40, max_age=49` |
| "Germany" | `country_code="DE"` |
| "China" | `country_code="CN"`, `culture_tag="asian"`, and **never** `JP` |
| "in Ohio" | `regions` carries `US` **and** `unmapped` carries Ohio (007 prompt rule 2) |
| "gamers", "who drive a Subaru" | present in `unmapped` |
| "women" | `gender="female"` |
| "wealthy" | `income_bands=["upper"]` |
| "with a university degree" | `education=["tertiary"]` |

**Judgement calls — no ground truth, so score only that the reading is auditable:**

- *"cautious"* → conscientiousness or neuroticism? Both defensible; the live run said
  conscientiousness.
- *"budget-conscious"* → income quintile, or unmappable? 007's own text claimed income;
  the live model returned `unmapped`, and is arguably right.
- *"a woman's guide to car insurance"* → is the audience women, or is that just what
  the copy is **about**? A spouse shopping for a partner is a plausible reader. The
  model will very likely set `gender="female"` because the word is there.
- *"a dad joke calendar"*, *"gifts for grandparents"* → same shape: a gendered or
  age-marked noun sitting in the **creative** rather than in the audience.
- *"young"*, *"old"*, *"middle-aged"* → which span? Added 2026-07-31, when
  [024](024-fuzzy-age-words-in-targeting.md) decided the **model** sets the bracket and
  discloses the phrase it read it from. So this is a judgement call by construction:
  assert a span exists and a `source_phrase` was recorded, never that the numbers match
  ours — 18–30 and 18–35 are both defensible, which is exactly why the project declined
  to legislate either. Note the ordering: *"in their 40s"* stays a **hard** requirement
  in the table above, because arithmetic has ground truth and a vague adjective does not.

For these, assert only that **a `source_phrase` was recorded** — that the
interpretation is inspectable, not that it matches ours. Report the distribution of
readings so a drift is visible without being a failure.

The reason this split matters is the same reason the noise floor matters: measure what
has ground truth, and be explicit about what does not. A suite that scores a
judgement call as wrong will be silenced the first time it fires on a defensible
answer.

## Scope

- ~20 descriptions, hand-labelled, covering each hard requirement above at least twice
  so one sentence and one rule are not confounded (015's limitation, in miniature).
- Per-field score, not a single number: "country 20/20, age 18/20, unmapped 15/20"
  localises a prompt regression. One aggregate score hides which rule broke.
- Include descriptions that should map to **nothing** (`"anyone"`) and ones that are
  adversarial about the rules (`"people in Tokyo"` must reach `JP` + `unmapped`).
- At least two **creative-not-audience** cases from the judgement list above. They are
  the ones most likely to surface the problem in the next section, and they are why
  that section is conditional rather than decided.

## Cost and where it runs

One call per case, ~20 cases, `gpt-5-mini` on a ~400-token prompt: **well under a cent
per run.** But it is still a paid, non-deterministic test, so it must not sit in the
default `pytest` run. Two options, both fitting existing convention:

- a `pytest.mark.paid` deselected by default (no marker convention exists yet), or
- `experiments/translation_eval.py` as a CLI, matching 014/015.

Prefer the CLI: it can print the per-field table, and the `experiments/` precedent
already separates paid measurement from the test suite. Add `--dry-run` (see
`app/seed.py`) so the case count and cost print before anything is spent.

## Open decision: should a demographic filter announce itself?

Surfaced 2026-07-27 while tracing how *"woman"* becomes a `WHERE` clause. **Recorded
here rather than decided, because it needs a product call.**

`gender` is treated as a *hard* attribute: the model fills the slot,
`targeting.resolve_target` copies it through untouched, and
`persistence.retrieve_panel` turns it into `gender = %s`. **No notice is emitted.** Trait readings get one — mapping
"cautious" onto conscientiousness is a judgement — but "woman" → `female` was assumed
not to be.

The creative-not-audience cases above are the counterexample. If the model reads
*"a woman's guide to car insurance"* as an audience filter, the panel silently loses
half the pool and the customer is never told a filter was applied on their behalf. That
is the **same class of defect as Ohio → the whole United States**, in the opposite
direction: instead of quietly widening the panel, it quietly narrows it. Ohio was
caught because the region path compares what was asked against what exists; nothing
compares the demographic path against anything.

The decision to make, once this run shows how often the model over-reads:

| option | cost |
|---|---|
| notice for **every** demographic filter | honest and uniform, but *"Read your target as women only"* on an explicit "women aged 30-40" is noise — and the age warning taught us that a notice firing when nothing happened trains the reader to skip the category |
| notice only for **inferred** filters | right in principle, but `resolve_target` cannot tell inferred from explicit — it never sees the description. It would need the translator to mark it, which puts the judgement back in the model |
| leave as is | acceptable **only if** the measurement shows over-reading is rare |

Note the middle option's shape: it is the same trade already made for traits, where
`source_phrase` carries the words the reading came from. Extending `source_phrase` to
demographic fields would let a notice quote the phrase and let a reader judge, without
`resolve_target` having to decide anything. That is the option this ticket should cost
out first.

**Partly answered elsewhere, 2026-07-31.** [024](024-fuzzy-age-words-in-targeting.md)
took the middle option for the **age** field specifically: the model sets a span for a
fuzzy word, records the phrase, and a `_reading` notice quotes both. So the extension
this section said to cost out first now has a committed consumer, and the age case
becomes the precedent the gender question can be decided against — with one caveat that
keeps this decision open rather than closed: age was decided *without* the measurement,
because a fuzzy word has no correct span to over-read, while "woman" does. The
frequency question that gates the gender call is still unmeasured.

Deliberately not built ahead of the measurement — a fix for a frequency nobody has
measured is a guess, and this run is cheap.

## What this does not cover

Whether the *retrieved panel* matches the target. After
[017](017-representative-sampling.md) that is exact by construction — trait levels become
`WHERE` clauses on the trait columns — so there is nothing probabilistic left to measure
on that side. This ticket stops at the struct, which is where the judgement lives.
