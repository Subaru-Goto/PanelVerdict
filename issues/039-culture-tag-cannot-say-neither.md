---
title: "Every country is western or asian, so the honest fallback never fires"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## Problem (found 2026-08-01, tracing "who decides that China is close to Japan?")

`CultureTag` has two members and **both are seeded**:

```python
COUNTRY_CULTURE_TAG = {Locale.US: WESTERN, Locale.DE: WESTERN, Locale.JP: ASIAN}
```

Prompt rule 1 tells the model to *"always set `culture_tag` to the coarse bucket the
place belongs to … leave it null only when the place genuinely spans both buckets"*. With
only two buckets on offer, the model files **every** country under one of them — so
`_SEEDED_BY_TAG[tag]` is never empty, rung 2 of the ladder always hits, and **rung 3
never executes.**

Verified live, one call per row:

| description | `culture_tag` the model chose | panel | coverage |
|---|---|---|---|
| `"people in Korea"` | `asian` | Japan | `approximated` |
| `"people in Vietnam"` | `asian` | Japan | `approximated` |
| `"people in Brazil"` | **`western`** | the US, Germany | `approximated` |
| `"people in Nigeria"` | **`western`** | the US, Germany | `approximated` |

Nigeria is not western. Brazil is not western. Both get a narrow, confidently-labelled
panel where the design intended the loud whole-pool answer.

## What is actually unreachable

| designed behaviour | what production does |
|---|---|
| `_resolve_region` returns `()` and `"unmatched"` | never returns it |
| `_resolve_regions`' whole-pool fallback, its last block | never runs |
| `"The panel spans the whole pool instead … not matched to the audience described — read it as a check on the wording rather than on that audience."` | never printed |
| coverage rung `"unmatched"` | unreachable for any live target |

The substitution is still *disclosed* — the warning names the tag and the countries — so
this is not a silent filter in the sense of
[037](037-income-reading-is-never-disclosed.md). It is worse in one specific way: the
disclosure is **mislabelled**. `approximated` and *"Treat as indicative"* claim a
cultural proximity that `western` does not carry for Nigeria, where `unmatched` and
*"read it as a check on the wording"* would have told the truth.

## Why the test suite could not catch it

`test_a_region_off_the_ladder_falls_back_to_the_whole_pool` passes, and asserts exactly
the behaviour described above as unreachable. It builds its input by hand:

```python
resolve_target(TargetRequest(regions=[RequestedRegion(label="Nigeria", country_code="NG")]))
```

**`culture_tag` defaults to `None`** — a state the live translator does not produce. So
the test pins a code path against an input the model never sends, and reads as coverage
of the fallback while proving nothing about it.

This is the third instance of one failure mode, and the pattern is the finding:

| defect | how it was found |
|---|---|
| [024](024-fuzzy-age-words-in-targeting.md)'s first fix shipped **inert** | a live call |
| [038](038-education-reading-is-never-disclosed.md) mis-filed `"left school at 16"` as a transcription | a live call |
| this ticket | asking who assigns the tag, then one live call |

None was findable by reading, and the suite was green for all three. The common shape:
**a test that constructs an input the model does not emit.**

## The fix, and why it is not a prompt change

Add the `CultureTag` members that let every place be described truthfully — `african`
and `latin_american` at minimum.

**No change to `targeting.py` is needed.** Two things already written handle it, and the
second has been waiting for a third tag since [007](007-build-targeting-query-translation.md):

```python
_SEEDED_BY_TAG = {tag: tuple(... if country_tag == tag) for tag in CultureTag}
...
if approximate:
```

`_SEEDED_BY_TAG` is a comprehension **over the enum**, so a new member arrives with a
bucket rather than a missing key — and a tag no seeded country carries yields `()`. The
guard in `_resolve_region` tests **truthiness**, not `is not None`, so an empty bucket
falls through to rung 3. Confirmed by emptying an
existing bucket and calling `_resolve_region` directly:

```
bucket for the tag -> ()   truthy? False
_resolve_region -> countries=() rung='unmatched'
resolve_target -> countries=['US','JP','DE'] coverage='unmatched'
  [warning] No Nigeria data, and no seeded region close enough to stand in for it.
  [warning] The panel spans the whole pool instead (the United States, Japan, Germany), so it
            is not matched to the audience described — read it as a check on the wording
            rather than on that audience.
```

**Rejected: letting the model emit `null` when nothing fits.** It was the first fix
considered and it is the wrong one. It asks the model to know **which countries we
seeded** — a fact about our database, not about Nigeria — and this module's own docstring
says why that is backwards: *"A request records the country as named, so the
approximating happens here, in code."* The model describes the place; code decides
whether the pool can serve it. Adding buckets keeps that split; a null clause breaks it.

## The framing worth keeping: `CultureTag` does two jobs

| job | wants |
|---|---|
| describe the place the customer named | a complete world taxonomy |
| index which seeded pool can stand in | only tags we have actually seeded |

A two-value enum where **both values are seeded** cannot express *"somewhere you don't
have"*, which is why every place gets forced into a bucket that resolves. The bug is
structural, not a missing row — and it is why the fix is *more buckets* rather than
*better bucket assignment*. **An unseeded bucket is a feature:** it is the only thing
that makes `unmatched` reachable.

That also settles where the enum stops. It needs enough members that every place is
describable, not one member per seeded country.

## What this does *not* fix, and should say so

Which bucket a place belongs to remains a **per-request model judgement with no
disclosure that a judgement occurred.** Compare the two sentences the product emits:

```
Read "good earners" as middle or upper income.
No China data; approximating with asian-region personas (Japan). Treat as indicative.
```

The first announces an inference. The second reads like a lookup — as though *"China is
asian"* were a fact the system holds, when it is the same class of model call as
`"good earners"`. This is the one model judgement left on the targeting path with no
`*_source_phrase` and no reading notice, and the mechanism to fix it exists three times
over after [038](038-education-reading-is-never-disclosed.md).

Left out on purpose: it is a second, larger change, and this ticket's value is that it
costs one enum edit. Worth a follow-up rather than a wider diff here.

## Also worth knowing before anyone reassures a customer about this

Approximating Korea with Japan buys **less** than the wording suggests, and that is in
our favour. `bigfive.py` is explicit: *"Shared across all countries: country does not
condition the Big Five μ."* So a "Japanese" persona differs from a "German" one only in
the demographic marginals it was sampled from and the country word in the vote prompt.
No culturally-conditioned psychology is being asserted, because the model contains none.
The substitution is a **demographic** proxy, not a cultural one.

## Done when

A target naming a country in no seeded bucket produces the whole pool, coverage
`"unmatched"`, and the wording-check warning — and a test builds its input the way the
**translator** does rather than the way a hand-written fixture does, so the third rung
stops being unreachable by construction.
