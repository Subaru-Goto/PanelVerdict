---
title: "Tech-debt / cleanup backlog"
labels: [wayfinder:note]
status: open
---

Deferred, non-blocking tidy-ups. Bundle into a **dedicated pure-refactor PR** (no
behaviour change, git-tracked renames) rather than mixing into feature work.

## Items

- **Shared pipeline HTTP + CLI helper.** `pipeline/build_leisure._http_fetch` is a
  near-verbatim copy of `build_oecd._http_fetch` (differing only in headers), and
  the two `if __name__ == "__main__"` blocks share a shape (`Locale(sys.argv[1])`
  -> dest dir -> build -> write -> print). `_SEX_CODE` also inverts
  `build_oecd._sex_to_gender`. Extract a small `pipeline/_sources.py` once the
  US/JP builders land and the real shape is known (flagged in the 006i slice-1
  review; deliberately not done mid-slice to avoid churning a merged module).

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
