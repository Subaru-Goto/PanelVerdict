---
title: "Per-vote cache: exact replay, and resume instead of re-run"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: [010c-panel-test-pipeline]
assignee: null
status: open
---

## Goal

Persist every vote, keyed on **`(persona, test, order)`**, and read the cache before calling
the model. A re-run of one test then replays exactly; a run that stopped half-way resumes
rather than restarting.

Assigned to 010's children from [008](008-build-panel-evaluation.md), which deferred it
because the key needs `test_id` to be a persisted entity — and this branch of the map is where
the run is created.

## This is the only exact-replay mechanism left

[002](002-decide-vote-schema.md) designed reproducibility on three legs: a seeded pool, a
pinned model, and `temperature≈0`. [003](003-decide-panel-model-and-provider.md) then found
the third unavailable — `gpt-5-mini` is a reasoning model and **rejects any non-default
temperature with a 400**. So per-vote caching is not a cost optimisation with a nice
side-effect; it is what remains of exact reproducibility, and 002's **test-retest QA metric**
is waiting on it.

The pool half is already exact: a persona is a pure function of the master seed
([006j](006j-persona-summary-embedding.md)), and `presentation_order` is reproducible per
seed ([008](008-build-panel-evaluation.md)). The votes are the only non-deterministic step
left, which is exactly what a cache pins.

## Design

**A `votes` table.** `VoteRecord` already carries every column it needs — `persona_id`,
`test_id`, `chosen_variant_id`, `presentation_order`, `reason` — so the schema is a
transcription, not a design. Follow the existing `schema.sql` + `apply_schema` pattern, and
extend `_REQUIRED_COLUMNS` if a column is added later (that probe exists because
`CREATE TABLE IF NOT EXISTS` silently accepts a stale table).

**Why the key is all three parts.** `persona` and `test` are obvious; **`order` is the
subtle one.** The same persona voting on the same pair in the opposite order is a *different
question* — 014 measured the model picking the first-shown option 0.66 of the time — so
caching on `(persona, test)` alone would serve a vote cast under one presentation as if it
were the other, and quietly destroy the counterbalancing 008 exists to guarantee.

**What invalidates an entry.** Anything that changes what the model was asked: the variant
text, the vote question ([015](015-task-framing-sensitivity.md) showed the verdict is
sensitive to the question's wording), the persona template, or the model id. A cache that
survives a prompt change is worse than no cache, because it silently mixes two experiments.
Decide whether that is enforced by including a hash of the request in the key or by
documenting a manual invalidation — and note that the pool's own convention is
**drop-and-reseed rather than migrate**, since the data is a cache of a pure function.

**Does the drop-and-reseed convention apply here?** Careful: votes are **not** a pure
function of the seed — they are paid model output. This is the first table in the project that
holds something that cannot be regenerated for free. That difference deserves an explicit
ruling, because the persona pool's "just drop it" habit would be expensive here.

## What this unlocks

- **Resume after a 402.** [003](003-decide-panel-model-and-provider.md)'s
  resume-after-top-up depends on it: with the cache, topping up the credit and re-running
  fetches only the missing votes. Without it, a run that dies at vote 180 costs 180 votes to
  get back. [010f](010f-budget-guard.md) builds on this.
- **Test-retest**, the QA metric 002 specifies and nothing can currently measure.
- **Cheap iteration** on everything downstream — 009's posterior, 011's report and
  [012](012-build-analyst-chatbot-tools.md)'s analyst can all be developed against a cached
  run instead of paying for votes each time. That may be the largest practical win, given the
  $10 cap.

## Out of scope

Budget checks and 402 detection → [010f](010f-budget-guard.md). This ticket makes resuming
*possible*; 010f decides when to stop and when to resume.
