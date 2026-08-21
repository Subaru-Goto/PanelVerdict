---
title: "Representative sampling: filter traits in SQL, drop the disposition vector"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: closed
---

## Goal

Stop matching Big Five with the embedding. Requested trait levels become **SQL filters
on the trait columns**, and the panel is then a **uniform sample within the filtered
set** — which is what makes it a realistic audience rather than a tail.

Signed off 2026-07-27. Supersedes the unlanded *"Retrieval relevance: does the vector
half beat a random draw?"*, whose question this decision makes moot.

## Why the vector goes

**It re-derives, approximately, something the columns hold exactly.** A persona's
neuroticism is a `double precision` value. The pipeline currently turns that number into
English at seed time, embeds it into 1536 dimensions, embeds the query the same way, and
compares angles — to answer a question `WHERE neuroticism > 0.5` answers exactly, for
free, with no model call.

That path existed because the vector originally covered **interests** — free text where
semantic matching genuinely earns its place, since no column can match "outdoorsy" to
"hiking". [006j](006j-persona-summary-embedding.md) dropped interests after four failed
designs and re-pointed the vector at demographics + Big Five, which are all already
structured columns. The tool outlived its justification.

**And top-*n* by cosine is actively wrong for a panel.** The pool is distributionally
grounded by construction — demographics from the OECD joint tables
([006b](006b-demographics-sampler.md)), Big Five from published norms conditioned on age
and gender ([006c](006c-bigfive-sampler.md)). So a uniform draw inside a demographic
filter *already* carries a realistic trait spread. Ranking by similarity and taking the
top 200 returns the extreme tail instead, and because one vector carries all five traits
plus the demographic prose, it skews the panel on dimensions nobody asked about. That is
the map's "panel sampling procedure" fog item, now sharp enough to close.

**Measured, not assumed.** A three-persona probe (2026-07-27, four embedding calls) on a
`neuroticism: high` query:

| persona | cosine distance |
|---|---|
| 42F US, neuroticism **high** | 0.7039 |
| 71M JP, neuroticism **high** | 0.7293 |
| 42F US, neuroticism **very_low** | 0.7602 |

The ranking is correct, so the mechanism works. But note the shape: absolute distances
all sit near 0.70 with a total spread of 0.056, and the demographic contrast moves the
score 0.025 — **45% as much as flipping the trait from very_low to high.** The signal is
a thin differential on a large common baseline, where the SQL equivalent is exact. n=1
per cell, so this illustrates rather than measures; it is recorded because it is the
evidence that prompted the decision, not as a result.

## Design

**Level → score bounds → `WHERE`.** `bucketize` maps a score to a level using
`_INNER_CUTOFF = 0.5` and `_OUTER_CUTOFF = 1.5`, with boundaries belonging to the inner
band (an exact `-1.5` is `low`, an exact `-0.5` is `medium`).

**Derive the bounds from those same constants — do not retype them in SQL.** A
`level_bounds(level) -> tuple[float | None, float | None]` beside `bucketize`, bound as
query parameters, keeps one source of truth. Two cutoffs written twice with different
inclusive sides is the drift this repo has been bitten by before (`_CELL`, `CONTROL_PAIR`).

Pin it with a test, but **not** the obvious round-trip one — see the directional decision
below. `bucketize(2.0)` is `very_high`, yet `2.0` satisfies `high`'s bound, so "every
score inside the bounds bucketizes back to this level" is false by design for the outer
four. What to assert instead is in that section.

**Then order by `md5(id || seed)`** — the sampling path that already exists and is
already tested. Uniform within the filtered set, reproducible per seed, independent of
insertion order.

## Decided: directional, not exact (signed off 2026-07-27)

A target asking for cautious people means *at least* cautious — excluding the most
cautious personas in the pool would be perverse. So a requested level is a **direction
from a threshold**, except at the middle where "average" genuinely means the middle:

| requested level | `WHERE` on that trait's column | share of a normal population |
|---|---|---|
| `very_high` | `score > 1.5` | ~6.7% |
| `high` | `score > 0.5` | ~30.9% |
| `medium` | `score BETWEEN -0.5 AND 0.5` | ~38.3% |
| `low` | `score < -0.5` | ~30.9% |
| `very_low` | `score < -1.5` | ~6.7% |

Note the consequence, which is the point of choosing this: `high` admits everyone
`very_high` admits, so the outer levels are nested rather than disjoint. That roughly
quadruples the candidate pool for a `high` request against an exact reading, which is
keeps the shortfall problem manageable.

The shares are the normal-distribution split the cutoffs already imply and which
[006c](006c-bigfive-sampler.md) records — not new constants. They shift per cell, since μ
moves with age and gender.

Two things follow for the bounds helper, both easy to get wrong.

It returns an **open bound** on the outer four levels (one side `None`), so the SQL
condition must be built from whichever bounds are present rather than always emitting
`BETWEEN`.

And the test asserts **nesting, not round-tripping**:

- every score satisfying `very_high` also satisfies `high` (and the mirror for the low
  side) — the property directionality exists to create;
- the threshold is exactly `bucketize`'s own boundary, so a score `bucketize` calls
  `medium` must fail `high`'s bound and vice versa. That is what ties the two to one
  source of truth without asserting a round-trip that directionality deliberately breaks.

A level-partition test would assert disjointness, pass on the wrong property, and hide a
`high` bound that had silently become exact.

## Consequence to handle, not discover

**Trait filters multiply**, even directional ones. `very_high` is ~6.7% of the
population, so two such traits is ~0.4% and a 5,000-pool yields ~22 personas — well under
n=200. Combined with a demographic filter it can reach zero. The directional reading helps
at `high` (~30.9%, so two of them is still ~9.5%) and barely helps at `very_high`, which
is where the risk actually lives.

v1 answer: **hard filter, and report the shortfall** — `PanelSelection` already emits a
warning when fewer personas match than were asked for, and 010 owns the consequence that
a thin panel changes what the verdict can express. Widening to adjacent levels with a
notice is the fallback *if* measurement shows shortfalls are common; do not build it
ahead of that evidence.

## Knock-on changes

- **`TargetQuery.disposition: str` is replaced by the trait levels as data**
  (`tuple[tuple[TraitName, TraitLevel], ...]` or similar hashable form). The rendered
  sentence has no consumer once the vector is gone. This also resolves two recorded
  items at once: the Primitive Obsession finding from 007's standards review, and the
  tech-debt note that [011](011-build-report-ui.md) needs the trait reading as data
  rather than only as notice prose.
- **`select_panel` stops needing an `Embedder`.** No embedding call per test at all —
  one less paid dependency on the product path.
- **`retrieve_panel` loses `disposition_embedding`**, and with it the `<=>` branch. The
  `md5` branch becomes the only ordering.
- **`personas.summary_embedding` stays.** Its remaining consumer is
  [012](012-build-analyst-chatbot-tools.md)'s `search_personas`, where free-text search
  over a persona summary has no column equivalent and the embedding does earn its place.
  Do not drop the column or the seed-time embedding.
- **`panel.render_trait_phrases` stays** — the vote prompt and the persona summary both
  use it. Only the *query* rendering goes away.

## Closed 2026-07-27 — what the build decided differently

Three things the ticket specified one way and the code does another. Each is a
deviation, so it is recorded rather than quietly absorbed.

**The bounds carry their comparison, not just their number.** `level_bounds(level) ->
tuple[float | None, float | None]` cannot express this domain: `medium`'s bounds are
**inclusive** (an exact `-0.5` renders as `medium`, so a request for it must admit that
persona) while every outer threshold is **exclusive** (an exact `1.5` renders as `high`,
so `very_high` must refuse it). A pair of bare floats leaves the inclusive side to
whoever writes the SQL, which is exactly the drift this ticket set out to avoid. So
`bigfive.LEVEL_BOUNDS` maps a level to a tuple of `(comparison, score)` pairs — one for
the four directional levels, two for `medium` — and the SQL builder emits one condition
per pair with the score bound as a parameter. It is a dict rather than a function
because a function wrapping a dict lookup is pure delegation.

**`TargetQuery.traits` is `tuple[TraitRequest, ...]`**, not `(TraitName, TraitLevel)`
pairs. `TraitRequest` is already the translator's output type, so nothing has to be
converted, and it carries `source_phrase` — which is the words the reading came from and
therefore the thing [011](011-build-report-ui.md) needs to show a reading the customer
can correct. `TraitRequest` became frozen so `TargetQuery` stays hashable.

**`render_trait_phrases` did not stay** — the knock-on list was wrong about this. The
*query* rendering was its only caller outside `panel.py`, and its partial-mapping
support existed only because a target names one or two traits, so once the query stopped
rendering, both the public name and the partial branch had zero production consumers.
It folded back into `_dispositions`, which now reads the phrase table directly, ordered
by `BigFive`'s own field order. The prompt and summary text are byte-identical — the
pool does not need re-embedding — and the domain-order claim is now pinned on
`persona_summary` itself, which is where it actually matters.

**Where the boundary is actually pinned.** The sweep and nesting properties are checked
in Python, against a second interpreter of `LEVEL_BOUNDS` written in the test — which can
say the table is self-consistent but not that *Postgres* compares it the way the table
means. So the four boundary scores (±0.5, ±1.5) are checked against the real query
instead: the level a score renders as must return it, and the level beyond must not.
Verified by mutation — writing `high` as `>=` turns that test red and leaves the Python
ones green, which is the drift this ticket was written to prevent.

## Requirement check

Dropping this does **not** weaken the advanced-RAG requirement, because the vector half
was its weakest third. Query translation (natural language → typed filters + the coverage
ladder) is untouched and is the named self-query pattern; the genuinely unstructured
retrieval moves to [018](https://github.com/Subaru-Goto/PanelVerdict/issues/124), where embeddings are
the only available tool.
