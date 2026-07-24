---
title: "Tech-debt / cleanup backlog"
labels: [wayfinder:note]
status: open
---

Deferred, non-blocking tidy-ups. Bundle into a **dedicated pure-refactor PR** (no
behaviour change, git-tracked renames) rather than mixing into feature work.

## Items

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
