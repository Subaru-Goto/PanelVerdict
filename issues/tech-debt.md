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
  - The `Embedder` protocol lives in `assembly` (pipeline) and is now imported by
    `targeting` (runtime). Two consumers, one home, and the convention elsewhere
    (`PanelLLM` in `vote`) is protocol-beside-consumer. Duplicating a two-line
    Protocol would satisfy structural typing and is the wrong answer; the reorg should
    give it a home both halves can import.
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

## `TargetQuery.disposition` keeps the prose, not the traits (noted 2026-07-27)

`disposition` is the rendered sentence the vector is built from, so which traits were
read at which level is recoverable only from the notice prose beside it. Fine while the
report shows sentences; the moment [011](011-build-report-ui.md) wants "neuroticism:
high" as a chip it needs the mapping as data.

Not added now because it would be a second representation of one fact with no consumer
— and the first thing to get wrong about this module was letting two values mean the
same thing. 011 is the ticket that will know whether it needs the structured form; add
it there, and derive the sentence from it rather than storing both.
