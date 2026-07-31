---
title: "Tech-debt / cleanup backlog"
labels: [wayfinder:note]
status: open
---

Deferred, non-blocking tidy-ups. Bundle into a **dedicated pure-refactor PR** (no
behaviour change, git-tracked renames) rather than mixing into feature work.

## Items

- ~~**Shared pipeline HTTP + CLI helper.**~~ Moot 2026-07-26: the duplication was
  between `build_leisure` and `build_oecd`, and `build_leisure` was deleted when
  006i closed. `build_oecd` is now the only builder, so there is nothing left to
  extract into a shared `pipeline/_sources.py`.

- **Module reorg (do after 006f closes).** `app/` is ~18 flat modules mixing two
  subsystems: the offline **pipeline** (`sampler`, `bigfive`, `assembly`,
  `persistence`, `seed`, `plausibility`, `schema.sql`) and the **runtime API**
  (`main`, `vote`, `verdict`, `llm`, `schemas`, `config`, `db`). `panel` belongs to
  both — it renders the vote prompt at runtime *and* the summary the pool build
  embeds — so the split has to decide where the rendering lives rather than
  assuming it is runtime-only. Group by subsystem — lean toward
  `app/pipeline/` (the sharper boundary) over a smaller `app/db/`. Pure move: keep
  `schema.sql` next to its reader, rewrite imports, change no logic.

  **Amended 2026-07-27 (007).** Two things the split now has to place, both of them
  straddling the boundary rather than sitting on one side:

  - `persistence.retrieve_panel` is a **runtime** reader in a module the list above
    calls pipeline. `load_pool` and `load_persona_sample` are pipeline readers, so the
    module genuinely serves both — like `panel`.
  - ~~The `Embedder` protocol has two consumers and one home.~~ Moot 2026-07-27:
    [017](017-representative-sampling.md) dropped the query embedding, so `targeting`
    no longer imports it and `Embedder` sits beside its only consumer again.
- ~~**`persist_persona` single cursor.**~~ Done 2026-07-26: dropping the
  `interests` table left one INSERT, so there is no second cursor to unify.

## A `VoteSplit` value object for `app/verdict.py` (noted 2026-07-27)

`(preferring_b, total)` travels through five signatures plus `Posterior` and `Batch`,
and `(rope, credible_mass)` through three. A small value object owning the validation
and the Beta parameters would absorb both clumps, and `_checked_split` is the seam it
would grow from.

Not done with 009 because the branch was already large and the refactor touches every
public signature in the module. Worth doing before 010 threads the same pairs through
the orchestrator.

Related, smaller: `tuple[float, float]` serves as both a credible interval and a ROPE
band, so `rope_verdict(interval, rope=...)` accepts them swapped and returns a wrong
answer rather than raising. Distinct types would catch it, but nothing type-checks this
repo today, so it would be documentation rather than enforcement.

And `app/main.py` reads `tally.counts["b"]` — fine while `/evaluate` hardcodes variants
`"a"`/`"b"`, a `KeyError` the moment 010 names them anything else.

## The four transport arguments want to be one type (noted 2026-07-31)

`api_key`, `base_url`, `provider`, `model` now travel together into all six model
constructors — `OpenRouterPanelLLM`, `analyst_chat_model`,
`OpenRouterTargetTranslator`, `OpenRouterEmbedder`, `OpenRouterJudge`,
`OpenRouterScreener`. [036](036-init-chat-model.md) is the evidence rather than the
cause: adding one field to that set cost fourteen mechanical insertions across eight
files, which is the clump and the shotgun surgery in one measurement.

A frozen value object built once at the endpoint layer — carrying the three transport
fields, with `model` staying a per-role argument since every role picks a different
one — makes the next such change a single line. The seam already exists: `main.py`'s
`_require_api_key()` plus `settings` is where all four are assembled today.

Deliberately **not** done inside 036: that ticket held behaviour constant and its
whole defence was a diff small enough to read against a bit-identical client. This
refactor changes six public signatures and belongs in the pure-refactor PR this file
is for.

Not to be confused with a fix for the *naming*: `provider` means "which langchain
integration package builds the client", not "which service is called" — the value is
`openai` while every request goes to OpenRouter. That reasoning lives on
`Settings.model_provider` and should move onto the value object with the fields.

## ~~`TargetQuery.disposition` keeps the prose, not the traits~~ (resolved 2026-07-27)

Resolved by [017](017-representative-sampling.md) rather than by 011, and for a
different reason than this note anticipated: once the trait levels became SQL bounds
the prose had no consumer at all, so there was never a choice between two
representations. `TargetQuery.traits` now carries the `TraitRequest`s themselves,
`source_phrase` included, which is the structured form 011 was going to need.
