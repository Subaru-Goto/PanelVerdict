---
title: "A vague income word silently excludes most of the pool"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found 2026-07-31, while working [024](024-fuzzy-age-words-in-targeting.md))

`"good earners"` becomes `income_bands=["upper"]`, which `resolve_target` expands to
quintiles `(4, 5)` and `retrieve_panel` turns into `income_quintile = ANY(...)`.

**No notice is emitted.** The panel loses 60% of the pool and the customer is never
told a judgement was made on their behalf. `"middle income"` is worse — quintile
`(3,)` alone, **80% excluded**, silently.

| band | quintiles | pool kept | pool excluded |
|---|---|---|---|
| `lower` | 1, 2 | 40% | 60% |
| `middle` | 3 | 20% | **80%** |
| `upper` | 4, 5 | 40% | 60% |

This is exactly as much a *reading* as `"cautious"` → conscientiousness. Traits
disclose theirs through `source_phrase` and a notice; income discloses nothing.

## Why this is the dangerous row, not merely an omission

A word can end up in one of four states, and the product handles three of them well:

| state | example | honest? |
|---|---|---|
| can't be expressed → **reported** | `"sporty"` → `unmapped` + warning | ✅ |
| read, applied, **disclosed** | `"cautious"` → conscientiousness, phrase shown | ✅ |
| read, applied, **not disclosed** | `"good earners"` → upper band | ❌ **this ticket** |
| could be read, isn't → reported | `"young"` before [024](024-fuzzy-age-words-in-targeting.md) | ⚠️ inert but honest |

The bottom row is *safe*: the panel stays wide and the customer is told the word did
nothing. This row narrows the panel on an inference made for them, invisibly. It is
the same defect class as Ohio → the whole United States — except Ohio gets a notice,
and [007](007-build-targeting-query-translation.md) caught Ohio precisely because the
region path compares what was asked against what exists. Nothing compares the income
path against anything.

## The mechanism already exists

[024](024-fuzzy-age-words-in-targeting.md) built it: the model records the words it
read a value from, presence of the phrase means "I inferred this", and
`resolve_target` emits a `_reading` notice. `resolve_target` never sees the
description, so phrase-presence is the only thing that can distinguish an inferred
band from an explicit one.

## The load-bearing decision: a third flat field, or generalise?

[024](024-fuzzy-age-words-in-targeting.md) added `age_source_phrase`. This ticket
would add `income_source_phrase`, and [038](038-education-reading-is-never-disclosed.md)
a third. **Three flat fields doing one job is the signal to generalise**, not to add a
fourth — and a general shape changes what the model emits, so it is a prompt change
as much as a schema one.

Decide this here, because 038 should reuse whatever this picks rather than adding
another field beside it.

## Then a copy decision, with two traps

**Speak bands, never quintiles.** [023](023-vote-feed-voter-details.md) established
that the wire speaks the band because the prompt never mentions a quintile — a notice
saying "quintiles 4-5" would leak an internal handle and describe something no
panelist was asked about.

**And say it in a reader's terms.** Income is ranked *within each country*, so
"upper" does not mean a currency amount. Candidates, none obviously right:

- `Read "good earners" as the upper income band.` — accurate, faintly internal.
- `Read "good earners" as the top 40% by income in their own country.` — reader-facing
  and carries the within-country ranking, but longer.
- Either, plus what it cost: `…which leaves out 60% of the pool.` The exclusion is
  arguably the most useful thing a customer could be told, and it is the number that
  makes a thin panel explicable. Weigh against
  [007](007-build-targeting-query-translation.md)'s lesson that notices firing on
  every run train the reader to skip the category.

## Scope

Income only. Two siblings, deliberately elsewhere:

- **Education** → [038](038-education-reading-is-never-disclosed.md), blocked on this
  ticket's schema decision.
- **Gender** stays out, gated on [016](016-translation-accuracy-golden-set.md)'s
  measurement of how often the model over-reads a gendered noun in the *creative*
  rather than the audience (`"a woman's guide to car insurance"`). Do not fix a
  frequency nobody has measured.

## Done when

A target naming a vague income word produces a panel *and* a notice a stranger can
act on, and the tests assert the disclosure rather than which band the model chose —
[016](016-translation-accuracy-golden-set.md)'s judgement-call rule, for the same
reason 024's tests never pin an age span.
