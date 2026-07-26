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
  subsystems: the offline **pipeline** (`sampler`, `bigfive`, `interests`,
  `content_checks`, `assembly`, `persistence`, `seed`, `stereotype_audit`,
  `plausibility`, `schema.sql`) and the **runtime API** (`main`, `panel`, `vote`,
  `verdict`, `llm`, `schemas`, `config`, `db`). Group by subsystem — lean toward
  `app/pipeline/` (the sharper boundary) over a smaller `app/db/`. Pure move: keep
  `schema.sql` next to its reader, rewrite imports, change no logic.
- **`persist_persona` single cursor.** Use one `with conn.transaction(), conn.cursor() as cur:`
  for both the persona INSERT and the interests `executemany`, instead of
  `conn.execute` (implicit cursor) + a separate `conn.cursor()`. Cosmetic
  consistency; functionally identical (reviewed 006f PR-2, banked here).
  **Obsolete 2026-07-26 if [006j](006j-persona-summary-embedding.md) slice 2
  lands first:** dropping the `interests` table removes the second cursor, so
  fold this into that PR rather than doing it twice.
