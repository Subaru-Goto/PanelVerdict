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
ticket deliberately. Standing at the third field, the saving turns out to be small — but
not for the reason first written down here. What a general carrier replaces is how the
*phrase* travels, which is the cheap part; what it costs is a change to what the model must
emit, on the one surface whose behaviour cannot be re-verified without paying, against two
fields already live. That is the whole argument, and it is about the prompt.

The first draft of this paragraph said instead that the three "render their readings
differently, so a shared carrier would unify only the transport" — and **review showed that
is false for two of the three.** Income and education render almost identically: an ordered
table, a joined list, one `Read "X" as … <noun>.` sentence. A shared *renderer* for those
two is arguable on its own merits and costs no prompt change; it is only the age span that
shares nothing. The field count and the sentence duplication are separate questions, and
the first draft used one to dismiss the other. Not extracted here — income's ordering table
doubles as its wording and education's does not, so the shared helper needs a contrived
identity map — but recorded as a real duplication rather than argued away.

**Copy: `Read "well-educated" as university-level education.`** A dedicated phrase table
in `targeting.py`, *not* `panel.py`'s — those describe a person ("completed a university
degree") for the vote prompt and do not compose into a list of what a filter kept. Each
level is named by the **institution** a person would name, which is what makes the guard
test possible: it asserts no wording equals its own enum value. The first version failed
that on its own terms — `secondary` was verbatim the handle, and the check it shipped with
(no underscores) would have passed `Read "well-educated" as tertiary education.` while
claiming to prevent exactly that. Found in review, and worth recording because the test
was the part that looked done.

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
the pool holds exactly three — but phrase-plus-levels emits a reading regardless. All
three fields share this, and **none** of them guards it: an earlier draft of this section
credited [024](024-fuzzy-age-words-in-targeting.md) with guarding the age equivalent, which
is wrong. `_resolve_ages` guards only the case where *neither* bound was set, which is the
same guard education already has via `not kept`; a phrase attached to an explicit 18–100
announces a filter on age exactly as an all-three-levels request does on education. Left
alone deliberately — it belongs to whichever ticket does all three, since fixing one
would read as a distinction between them.

**An empty-string phrase was announcing `Read "" as …`, on all three fields.** Found in
review. The guard was `is not None`, while the prompt instruction is to leave the field
*empty* — and an empty string is what a JSON emitter reaches for when told that, so the
schema's own default was not the only way to get there. Now falsy on age, income and
education together, pinned by one test that asserts all three, because a guard fixed on
one field would read as a deliberate distinction. This is the second time in this arc that
the defect lived in the gap between what the prompt *says* and what the code *checks*.
