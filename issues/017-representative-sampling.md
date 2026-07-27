---
title: "Representative sampling: filter traits in SQL, drop the disposition vector"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
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

Pin it with a round-trip test: for every level, scores sampled inside the returned bounds
must `bucketize` back to that level, and scores just outside must not. That tests the
inverse relationship rather than restating either implementation.

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
what keeps the shortfall problem below manageable.

The shares are the normal-distribution split the cutoffs already imply and which
[006c](006c-bigfive-sampler.md) records — not new constants. They shift per cell, since μ
moves with age and gender.

Two things follow for the bounds helper. It returns an **open bound** on the outer four
levels (one side `None`), so the SQL condition is built from whichever bounds are present
rather than always emitting `BETWEEN`. And the round-trip test has to assert **nesting**
for the outer levels — every score satisfying `very_high` must also satisfy `high` —
rather than the disjointness a level-partition test would naturally check.

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

## Requirement check

Dropping this does **not** weaken the advanced-RAG requirement, because the vector half
was its weakest third. Query translation (natural language → typed filters + the coverage
ladder) is untouched and is the named self-query pattern; the genuinely unstructured
retrieval moves to [018](018-audience-research-knowledge-base.md), where embeddings are
the only available tool.
