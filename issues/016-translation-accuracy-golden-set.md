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

## Cost and where it runs

One call per case, ~20 cases, `gpt-5-mini` on a ~400-token prompt: **well under a cent
per run.** But it is still a paid, non-deterministic test, so it must not sit in the
default `pytest` run. Two options, both fitting existing convention:

- a `pytest.mark.paid` deselected by default (no marker convention exists yet), or
- `experiments/translation_eval.py` as a CLI, matching 014/015.

Prefer the CLI: it can print the per-field table, and the `experiments/` precedent
already separates paid measurement from the test suite. Add `--dry-run` (see
`app/seed.py`) so the case count and cost print before anything is spent.

## What this does not cover

Whether the *retrieved panel* matches the target — that is
[017](017-retrieval-relevance.md). This ticket stops at the struct.
