---
title: "Nothing tells a customer which kind of person preferred which variant"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: null
status: open
---

## The question no tool answers (raised 2026-08-02, asking what value the analyst adds)

A customer has just read *"B preferred, 68% chance."* The next three questions are
predictable, and only two of them land:

| question | tool | answered? |
|---|---|---|
| "Why did B win?" | `read_reasons` | yes — the sentences panelists actually wrote |
| "Who was on the panel?" | `analyze_results` | yes, built by [025](025-analyst-panel-composition-facts.md) after a live turn died without it |
| **"What kind of people preferred B?"** | — | **no** |
| **"Which traits moved the decision?"** | — | **no** |

The last two carry the commercial value. *"B wins"* is a verdict; *"B wins with the
cautious half and A wins with the curious half"* is a decision about who to send it to.

## The data is already joined; the aggregation throws it away

`votes_with_voters` produces per-vote records carrying **both** the voter and their
`chosen_variant_id`, and that payload is already on the wire.
`analyze_results` recomputes composition from those same votes and **discards the
variant** — it returns `genders: dict[Gender, int]` for the whole panel, never crossed
with what those voters chose.

So this is a `GROUP BY` over data already in memory, not a retrieval problem.

## Not the vector store, and this is the third time the same argument applies

The suggestion that prompted this ticket was to put a Big Five summary in the vector
store. **It belongs in neither** — the five traits are already stored as exact
`double precision` columns, and an embedding of *"curious and imaginative, drawn to new
ideas"* is a lossy paraphrase of `openness = 0.82`. Regressing on a 1536-dim encoding of a
sentence generated *from* the number you wanted is strictly worse than reading the number.

[017](017-representative-sampling.md) already made this argument to delete the targeting
vector — *"the vector re-derived approximately what the columns hold exactly"* — and it
holds here unchanged. Nothing about this feature needs new storage.

## The load-bearing decision: ordinal levels, not z-scores

The **wire** deliberately does not carry the numbers.
[023](023-vote-feed-voter-details.md):

> *Trait scores travel as `TraitLevel`s, not z-scores, and income as the band, not the
> quintile — both are the words the vote prompt was rendered from, so what the report
> shows about a voter cannot drift from what the panelist enacted.*

And [035](035-panel-scope-comes-from-the-client.md) has the analyst's scope come from the
client payload. So the analyst sees **five ordinal levels**, by design.

**Use the levels.** A level is what the panelist was actually asked to embody, so an effect
measured on it is an effect on something that happened. A z-score would measure a variable
the prompt never expressed, and reaching into the DB for it would break 023's guarantee
that the analyst knows only what the panelist was told. The ordinal is not a compromise
here — it is the more valid choice.

## Not a regression, and the reason matters

[014](014-targeting-manipulation-check.md) already answered *"do traits move votes?"* —
**yes, 32.5% of votes against an ~11% noise floor.** But it earned that with a
**controlled** design: paired stimuli and a trait-free arm derived from
`render_demographics_prompt` so wording and traits could not vary together.

An observational cross-tab on one panel is much weaker, for a reason built into the pool:
**Big Five μ is conditioned on age and gender** ([006c](006c-bigfive-sampler.md)), so
traits and demographics are correlated *by construction*. "Openness drove the preference"
and "openness tracks age, and age drove the preference" are not separable from this data.
Testing five traits at once also multiplies false positives.

So the deliverable is **descriptive, with no causal claim**: per trait, how the A/B split
differs across levels, each with an interval, and an explicit *"too few to say"* where a
cell cannot support a statement. Same discipline [020](020-probability-not-label.md)
imposed on the top-level verdict, for the same reason.

## Cell sizes, derived rather than assumed

`bucketize` cuts at ±0.5 and ±1.5. Against a standard normal that puts, per trait:

| level | share | of a 200-panel | per variant |
|---|---|---|---|
| very_low | 6.7% | ~13 | **~7** |
| low | 24.2% | ~48 | ~24 |
| medium | 38.3% | ~77 | ~38 |
| high | 24.2% | ~48 | ~24 |
| very_high | 6.7% | ~13 | **~7** |

Approximate — μ moves with age and gender, so a real panel's mix shifts. But the shape is
the point: **the extreme levels carry about seven votes per variant**, which supports no
claim at all. Any design that prints a percentage per cell will overclaim on the two rows
customers find most interesting. Collapsing to three bands (low / medium / high) is the
obvious mitigation and should be costed against losing the very_high row that a targeting
question most often asks about.

## What this means for `search_personas`

Recorded here because this ticket is what supersedes it. `search_personas` is the analyst's
pgvector retrieval, and it is **not valuable for this question or any other a customer
asks**: top-*n* by cosine returns a handful of personas out of the panel, so it says nothing
about the panel as a whole — which is the same defect [017](017-representative-sampling.md)
measured when it deleted the targeting vector, *"top-n by cosine returns the extreme tail
where a panel needs a spread"*, in user-facing terms. It is also **variant-blind**: asked
which people preferred B, it can return an A-voter.

Kept for now, deliberately, because it is the standing demonstration of vector retrieval
and costs one column and one query. **The keep-or-remove call is deferred until this ticket
ships**, at which point the useful version of the question exists and the tool can be
judged against a real alternative rather than against nothing.
[018](018-audience-research-knowledge-base.md) remains where embeddings actually earn their
place, over prose no `WHERE` clause could match.

## Done when

A customer can ask which kind of person preferred a variant and get an answer that names
the split, carries its uncertainty, and says "too few to say" rather than printing a
percentage over seven votes.
