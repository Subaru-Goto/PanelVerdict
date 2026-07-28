---
title: "Vote feed: show who voted, not their database handle"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [011-build-report-ui]
assignee: null
status: open
---

## Goal

Replace the `US-00042 → A` line in the reasons feed with the voter as a
person: demographics at a glance, Big Five on demand. A persona id is a
debugging handle — it identifies a row, not a reader — and the user's read
on the 011b report was that it adds nothing. What makes a reason worth
reading is who gives it: *"34, DE, tertiary, high conscientiousness"*
next to a cautious rationale is evidence; `US-00042` is noise.

## Why the wire has to change

`Vote` carries `persona_id`, `chosen_variant_id`, `reason` — nothing about
the voter. The pipeline holds the full matched personas when it builds the
response, so this is enrichment at assembly time, not a new query. The
personas are synthetic, so there is no privacy question — but say so in
the UI copy if the demographics look real enough to raise it.

## Shape (to be confirmed at implementation)

- Backend: each vote gains a `voter` summary — `country`, `age`, `gender`,
  `education`, `income_quintile`, and the five trait levels. Keep
  `persona_id` in the payload for reproducibility/debugging; the frontend
  just stops leading with it.
- Frontend: the vote row leads with the choice and the reason; a compact
  demographic line replaces the id; Big Five levels behind a disclosure
  (`<details>` or a chip row) so the feed stays scannable.
- Decide at implementation: whether the demographic line is composed
  client-side from fields (flexible, more copy decisions) or the backend
  ships a ready sentence (one place to word it, consistent with how
  notices already work).

## Open questions

- Payload size: 200 votes × a voter object is fine today; check nothing
  downstream assumes the old shape (cache fingerprints hash prompts and
  options, not response bodies — assert, don't assume, as in 022).
- Whether trait levels show as words ("high conscientiousness") or the
  chip style 011b already uses for target traits — reusing the chip keeps
  one visual language for traits everywhere.

## Done when

- No raw persona id visible in the rendered report.
- A vote row shows demographics inline and Big Five on demand.
- Backend and frontend suites green; exfiltration rule holds (voter fields
  render as plain text like every other model-adjacent string).
