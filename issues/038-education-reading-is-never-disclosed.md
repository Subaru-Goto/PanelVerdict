---
title: "An education filter is applied without saying so"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [037-income-reading-is-never-disclosed]
assignee: null
status: open
---

## Problem (found 2026-07-31, alongside [037](037-income-reading-is-never-disclosed.md))

`resolve_target` copies education through — `tuple(dict.fromkeys(request.education))` —
and `retrieve_panel` turns it into `education = ANY(...)`. **No notice is emitted.**

The pool holds three levels: `below_secondary`, `secondary`, `tertiary`. So
`"university graduates"` keeps one of the three and drops the other two, and the
customer is not told a filter was applied.

Blocked on [037](037-income-reading-is-never-disclosed.md) rather than merged into it:
037 has to decide whether a third `*_source_phrase` field is added or the shape is
generalised, and this ticket should reuse that answer instead of adding another field
beside it.

## Why it is the mild sibling, and worth doing anyway

Education differs from income in a way that matters for the fix: **most of its
mappings are transcriptions, not judgements.**

- `"university graduates"`, `"with a degree"` → `tertiary`. A vocabulary mapping. There
  is little for a reader to disagree with.
- `"well-educated"`, `"highly educated"` → ? A genuine judgement. Does it mean tertiary
  only, or tertiary plus secondary? Nobody has decided, and the model currently decides
  silently every time.

[024](024-fuzzy-age-words-in-targeting.md)'s rule handles both without a new mechanism:
the model records a phrase **only when it inferred**, so the transcribed cases stay
quiet and the judged ones speak. That is the same asymmetry as `"in their 40s"` (no
phrase) versus `"young"` (phrase) — which is already live and verified.

So the expected outcome is that most education targets emit nothing, and that is
correct rather than a sign the fix did not work. Worth stating in the test names, or a
reader will "fix" the silence later.

## Watch for

**Do not describe a level by its enum.** `below_secondary` is an internal handle;
[023](023-vote-feed-voter-details.md)'s rule is that the reader gets words a person
could use. Whatever the notice says, it must not be `Read "well-educated" as
['tertiary']`.

**Education is a stronger over-reading risk than it looks**, for the reason
[016](016-translation-accuracy-golden-set.md) records about gender: a word can sit in
the *creative* rather than the audience. `"a graduate's guide to first jobs"` is
plausibly aimed at graduates — or at their parents. If the model reads it as an
audience filter, two thirds of the pool vanish quietly. That is the same shape as
`"a woman's guide to car insurance"`, and it is why disclosure matters more here than
the tidiness of the mapping suggests.

## Done when

An inferred education reading is disclosed in a stranger's vocabulary, a transcribed
one stays silent, and both behaviours are pinned by name so neither is mistaken for a
bug later.
