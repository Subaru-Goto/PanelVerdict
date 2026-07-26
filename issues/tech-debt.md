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
- ~~**`persist_persona` single cursor.**~~ Done 2026-07-26: dropping the
  `interests` table left one INSERT, so there is no second cursor to unify.
