---
title: "Per-vote cache: exact replay, and resume instead of re-run"
labels: [wayfinder:task]
parent: 010-assemble-orchestrator-graph
blocked_by: [010c-panel-test-pipeline]
assignee: Subaru-Goto
status: closed
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

## Closed 2026-07-28

The cache ships, and the key is **not** the `(persona, test, order)` triple above — it is
the **fingerprint of the question itself** (decided with the user): a sha256 over the
adapter's configuration plus the exact request strings (`app/vote.py:
vote_fingerprint`). That one move dispatched three of this ticket's open questions at
once:

- **Invalidation** (the hash-vs-manual fork): hash-in-key, so it is automatic and total —
  a changed persona template, headline, question wording, or model *is* a different
  fingerprint, and the stale-cache failure this ticket calls "worse than no cache" is
  unrepresentable rather than guarded against.
- **`test_id` never became a persisted entity.** Re-run identity is content identity:
  same inputs fingerprint the same, so a second `/evaluate` finds its votes with no
  "tests" table and no way for callers to name a prior run. `test_id` stays a correlation
  id, stored as provenance — a cached vote keeps the id of the run that **paid** for it.
- **`order` fell out of the key.** A swapped order swaps `option_1`/`option_2` inside the
  fingerprint, so the 0.66 counterbalancing trap cannot fire; the triple survives as
  queryable columns beside the key.

**The adapter's whole ask is in the key, not just the model id.** `OpenRouterPanelLLM`
also binds the vote question ([015](015-task-framing-sensitivity.md) measured the verdict
moving with its wording) and the reasoning effort, so `PanelLLM` grew one attribute —
`configuration`, everything the adapter contributes to the question — and a knob added
later joins the key by extending that string, not the protocol.

**Drop-and-reseed ruled out — the ledger is append-only** (the explicit ruling this
ticket asked for). Votes are paid output, the first non-regenerable table in the project:
`store_votes` is `ON CONFLICT DO NOTHING`, never update, and there is deliberately **no
foreign key to personas**, so reseeding the pool cannot cascade into the ledger.

**The subtle mechanical bit:** presentation orders are fixed per chunk *before* the
hit/miss split (`collect_panel_votes` accepts pre-assigned orders) — a fresh draw over
the misses alone would re-pair panelists with positions and turn every would-be hit into
a paid miss. Cached and fresh votes merge back in panel order with `None` usage entries,
so `PanelVotes`' two documented invariants hold and nothing downstream can tell a cached
vote from a paid one — which is what makes resuming statistically legitimate.

**Ops note:** an existing dev database predates the `votes` table; re-running the seed
(idempotent, "0 written") applies the schema. Until then `/evaluate` fails loudly with
`UndefinedTable` — nothing silent.

**The review caught two real holes, both fixed:**

- **Durability.** `store_votes` ran inside the request's open transaction, so the write
  was a savepoint that only committed at a clean request exit — a run dying at vote 180
  would have rolled back all 180 stored votes, defeating this ticket's headline promise.
  The pipeline now commits per chunk, with a test that stored votes survive a rollback.
- **The scaffold was outside the key.** The human message wraps the options in fixed
  scaffolding ("Here are two options…" plus the answer instruction); editing it changes
  the ask without changing the fingerprint. `configuration` is now derived from
  `build_vote_messages` itself, rendered with blank inputs — a template edit changes the
  key with nobody remembering to mirror it — and is JSON-framed like the fingerprint.

**Known limits, on the record:**

- *Replay is exact downstream of targeting.* `/evaluate` re-translates the description
  through a live model each run; a translation that comes back different changes the
  panel, and with it the chunk composition and fingerprints. The failure is fail-safe —
  paid misses, never a wrong vote served — but "the votes are the only non-deterministic
  step left" holds per-panel, not per-description. Caching the translation is its own
  decision, not smuggled in here.
- *The structured-output schema* (`PanelVoteOutput`'s field names and descriptions) also
  shapes the ask and is not in the key. Accepted as residual: a schema change breaks
  parsing of old-shape answers loudly, and keying on it would mean fingerprinting a
  generated JSON schema — machinery out of proportion to the risk today.

`apply_schema`'s stale-column error no longer says "drop the database" — that advice
predates a database holding paid output; it now says to drop and reseed the personas
table only.

Unlocked but deliberately not run here: test-retest (002's metric — needs a paid run,
010f territory) and resume-after-402 (010f builds the trigger; the mechanism now
exists).
