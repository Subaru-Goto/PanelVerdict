---
title: "An education filter is applied without saying so"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [037-income-reading-is-never-disclosed]
assignee: Subaru-Goto
status: closed
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

## Delivered 2026-07-31

`education_source_phrase` on `TargetRequest`, prompt rule 6, and `_resolve_education`
in `targeting.py` — which owns the dedup that used to sit inline in `resolve_target`,
because a repeat would have read back as "secondary or secondary education".

**The generalise-at-the-third-field prediction was checked here and reversed.**
[037](037-income-reading-is-never-disclosed.md) recorded that three flat fields would be
the signal to replace them with one general carrier, and left the migration to this
ticket deliberately. Standing at the third field, the saving turns out to be small: each
field renders its reading differently — a span, a set of bands, a set of levels — so a
shared carrier would unify only the *transport* of the phrase, never the sentence. What
it would cost is a change to the prompt, the one surface whose behaviour cannot be
re-verified without paying, against two fields already live and verified. So: three flat
fields, and the prediction is on the record as tested rather than quietly dropped.

**Copy: `Read "well-educated" as university-level education.`** A dedicated phrase table
in `targeting.py`, *not* `panel.py`'s — those describe a person ("completed a university
degree") for the vote prompt and do not compose into a list of what a filter kept. A test
asserts the table covers every enum member and that no wording contains an underscore,
which is the cheapest available proxy for "no internal handle leaked".

### The live run moved a prompt rule, again

Three descriptions, then two more after the fix. The asymmetry held first time —
`"well-educated"` → `tertiary` **with** a phrase and a notice; `"university graduates"` →
`tertiary` **silent** — but the third case failed in a way only a live call could show:

| description | before | after |
|---|---|---|
| `"left school at 16"` | `below_secondary`, **no phrase** | `below_secondary`, phrase recorded |

The rule as first written listed `"left school at 16"` among the transcriptions. It is not
one: it names an **age**, and reaching an attainment level from it needs a specific
country's school system — in Germany that path runs through Hauptschule. So the rule now
says a leaving age or a school-system stage names no qualification, and reaching a level
from it is a reading. This is the second consecutive ticket where the mistake was in
prose the whole suite passes over, and the second where a paid call under a cent found it.

### Still open, and named because the fix does not reach it

**The over-reading case is the silent case.** This ticket's own "watch for" flags
`"a graduate's guide to first jobs"` — a qualification sitting in the *creative* rather
than the audience. The model would read that as a transcription and stay silent, which is
exactly when a reader most needs telling. Disclosure keyed on inference cannot catch a
confident misreading, so the gap is the gender question in
[016](016-translation-accuracy-golden-set.md) wearing different clothes, and it stays
gated on that ticket's measurement rather than guessed at here.

**A request naming all three levels would still announce a filter.** It filters nothing —
the pool holds exactly three — but phrase-plus-levels emits a reading regardless.
[024](024-fuzzy-age-words-in-targeting.md) guards the equivalent case for age (a phrase
with no span narrows nothing, so it says nothing) and income has the identical hole. Left
alone because fixing it on one field and not the other would be worse than the hole:
it belongs to whichever ticket does both.
