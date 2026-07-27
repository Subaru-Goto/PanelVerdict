---
title: "Build hybrid targeting / query translation (the RAG requirement)"
labels: [wayfinder:task]
parent: 000-map
blocked_by: [006-build-persona-pool]
assignee: null
status: closed
---

## Goal

Natural-language target description → **structured SQL filters + embedding query** (self-query / query translation — this IS the "advanced RAG" requirement).

- hybrid retrieval: SQL for hard attributes, vector for fuzzy attributes,
- panel sampling: 100–300 personas, **all target-matched** (see the control-group amendment below),
- **fixed seed** → reproducible panels.

## Amended 2026-07-26 — no control group in a production panel

The panel was specified as ~80–90% target-matched plus a 10–20% random control.
**Dropped: a production panel is one target group, and the Bayesian layer reads the
preference off it.** Controls belong to the testing track — 014's harness — not to
the product path.

The reason is that the control changes no decision the customer makes. If B wins
70/30 in the target and also 70/30 in a random panel, the recommendation is still
"ship B"; the control only annotates the verdict, it never redirects it. Meanwhile
it costs: those 20–40 votes come out of the target group and widen the credible
interval on the number actually reported, and at 10–20% of a panel the control's own
preference is pinned only to roughly ±22 points, so it is a blunt annotation at that.

Two distinctions that were being conflated:

- **Validation control vs. per-test control.** The grounding research endorses a
  control group *for isolating targeting effects*, and [001](001-decide-persona-schema-and-seed.md)
  cites it. That is a one-off experiment, already answered at the mechanism level by
  [014](014-targeting-manipulation-check.md) (32.5% of votes move against an ~11%
  noise floor), with the full version — the Upworthy study — out of scope on the map.
  A control in *every* customer test is a weaker rerun of a check already done
  properly.
- **The useful comparison is segment vs. segment, not target vs. noise.** "Should I
  write different copy per audience?" is answered by comparing two target segments,
  which is a product feature worth building deliberately if wanted. Comparing a
  target against random strangers answers almost nothing, imprecisely.

Knock-on: [009](009-build-bayesian-layer.md) fits one posterior rather than two;
[010](010-assemble-orchestrator-graph.md)'s report payload drops its "segment
breakdown target vs. control"; [002](002-decide-vote-schema.md) is untouched, since
`VoteRecord` needs no matched/control label. No `control_fraction` parameter either
— an unused knob in product code is generality with prose for a justification, and
`experiments/` is where controls live.

## Amended 2026-07-26 — `culture_tag` lives in code, and here is when that flips

The ladder below assumes a stored `culture_tag`. There isn't one: 006b never added
it, and `schema.sql` carries only country. **For v1 it stays in code** — the tag is
a pure function of country (US/DE → Western, JP → Asian), so a column would be a
denormalised copy that can drift from what it derives from, and at three countries
the mapping is three lines. The middle rung is `WHERE country IN (…)`.

**The trigger for moving it into the database is not "many countries" —
it is countries becoming *data* rather than *code*.** `Locale` is a Python enum, so
today adding a country already requires a deploy and the tag can ride along in the
same commit. The moment the country list comes from a table, so a country can be
seeded without deploying, the tag has to follow it there or the two silently
disagree. Note what is *not* a reason: `country IN (…)` does not degrade with more
countries — the list is bounded by the country count and Postgres handles that
trivially. Moving it for performance would be moving it for the wrong reason.

Two things to get right whenever that day comes: the tag belongs on a `countries`
table keyed by country, **not** repeated on every persona row (one row per country,
not per person), and the coarse-tag vocabulary itself needs a source — "Asian /
Western" is a v1 convenience that 001 already flagged as not a census category, and
it will not survive a long country list without one.

Unblocked 2026-07-26: 006 closed with 006g.

## Region coverage + fallback (from the 2026-07-21 grounding grill; see [001](001-decide-persona-schema-and-seed.md) amendment)

The pool is **country-grounded** with a derived **`culture_tag`** (Asian/Western). v1 seeds JP/US/DE. **Coverage = the seed list**, so query translation must handle out-of-coverage targets:

- **Graceful degradation ladder:** `country → culture_tag → (global)`. e.g. a "China" target has no seeded country → fall back to `culture_tag = Asian` (currently only Japan is seeded).

## Amended 2026-07-26 — what the vector half now carries

[006j](006j-persona-summary-embedding.md) makes the fuzzy half a single
`personas.summary_embedding` over a templated summary of **demographics + Big
Five**. Mechanism unchanged (hybrid: SQL for hard attributes, vector for fuzzy);
coverage narrower:

- **In coverage:** dispositional and demographic targets — *"cautious,
  budget-conscious homeowners in their 40s"* maps onto neuroticism,
  conscientiousness, income quintile and age.
- **Out of coverage:** activity or lifestyle targets — *"outdoorsy people"*,
  *"gamers"*. Personas carry no interest or leisure field
  ([006i](006i-leisure-profiles.md) closed; [006d](006d-interests-synthesis.md)
  superseded), so nothing can match.

An out-of-coverage *attribute* must be surfaced the same way an out-of-coverage
*region* is — **never silently answered** with a panel matched on the remaining
words of the query, which would look like a targeted panel and be a random one.
- **Never silent.** Every fallback must be **surfaced to the user** — e.g. *"No China data; approximating with Asian-region personas (currently Japan only). Treat as indicative."* Silent substitution risks false confidence, and Japan is a weak proxy for China (different demographics/interests/language).
- Empty result is an honest outcome when even the coarse tag has no seeded coverage — report it, don't fabricate a panel.

## Closed 2026-07-27 — what shipped

`app/targeting.py` (`resolve_target`, `select_panel`, `TargetTranslator`),
`retrieve_panel` in `app/persistence.py`, the request/query schemas in
`app/schemas.py`, and `OpenRouterTargetTranslator` + `build_target_messages` in
`app/llm.py`.

The shape is **request → query → panel**, and the split is what makes "never
silent" enforceable rather than remembered:

- A **`TargetRequest`** is what the model read out of the description, recording the
  country *as named* plus its coarse tag. Note the asymmetry this buys and the one it
  does not: a **region** gap is surfaced by construction, since code compares the
  named country against the seeded set. An **attribute** gap is not, and cannot be —
  `resolve_target` never sees the description, so nothing but the translator can
  notice that "gamers" went unanswered. `unmapped` rests on prompt rule 4. A translator emitting `Locale` would have
  had to answer "China" with Japan inside the model call, where nothing can attach a
  notice to the substitution.
- **`resolve_target`** walks the ladder in code — country → culture tag → nothing —
  per region, so "the US and Nigeria" keeps the US, warns about Nigeria, and still
  returns a panel.
- **`retrieve_panel`** filters on hard attributes and *ranks* on the vector. Filters
  decide eligibility (a target asking for Germans is never served Americans at any
  similarity); the disposition only orders the eligible, because "cautious" is a
  matter of degree with no cautious/not-cautious line in the pool to filter on.

Two design points worth carrying forward:

- **`TargetQuery.countries` is always explicit.** The global rung lists every seeded
  country rather than leaving the filter off, so an empty tuple means *no coverage*
  and not *no filter*. Had the two shared one value, retrieval could not tell
  "everyone" from "nobody" — the one confusion that turns an honest empty result into
  a random panel.
- **The query is written in the persona summary's own words.** Requested trait levels
  render through `panel.render_trait_phrases`, the same 25-phrase table the embedded
  summary was built from. A paraphrase would compare two vocabularies. Partial by
  design: a target naming two traits does not get the other three filled in at
  medium, which would put words in the query the customer never asked for.

Reproducibility is a `seed` parameter defaulting to `PANEL_SEED = 0`, so one target
draws one panel run after run; a caller measuring sample stability passes its own.
No disposition means nothing to rank by, so the panel is ordered by `md5(id, seed)` —
independent of insertion order and free of the server-side random state a second
query in the same session could disturb. Ties break on `id`, because duplicate
summaries embed identically (two 34-year-olds at the same rendered levels are the
same text) and an unstable order would vary the panel for no visible reason.

## Amended 2026-07-27 — the vector half covers less than this ticket claimed

Verified against five live `gpt-5-mini` translations. The "In coverage" example above
is *"cautious, budget-conscious homeowners in their 40s"* mapping onto neuroticism,
conscientiousness, income quintile and age. What actually happened:

| phrase | claimed | observed |
|---|---|---|
| "in their 40s" | age | ages 40-49 ✅ |
| "cautious" | neuroticism | **conscientiousness: high** |
| "budget-conscious" | income quintile | **`unmapped`** |
| "homeowners" | — | `unmapped` ✅ |

So one of the four attributes the example promised arrived, one arrived read as a
different trait, and one the ticket counted as in-coverage was reported as
unmappable. **This is not a defect** — the notice is honest, and the panel is not
falsely labelled. But the dispositional half is thinner in practice than the
amendment implies, and a report that leans on it should say what was read rather than
what was asked. `TraitRequest.source_phrase` exists for exactly that.

The trait reading is also a genuine judgment call rather than an error: "cautious"
plausibly reads as either high conscientiousness or high neuroticism, and nothing in
the pool disambiguates them. Which is why the reading is shown back.

## Amended 2026-07-27 — sub-national places are now surfaced

The live run caught the ticket's own rule being broken. *"outdoorsy gamers in Ohio"*
resolved to the whole United States with **no notice**: the model mapped Ohio onto
`US` and left it out of `unmapped`, so a panel drawn for 340 million people was
labelled as Ohio's.

Within-country region is out of scope for v1 by the map's own decision, which makes
it precisely a coverage gap to surface rather than absorb. The prompt now requires any
place narrower than a country to appear in **both** `regions` (under its country) and
`unmapped`. Confirmed on re-run.

The general lesson, which generalises past geography: an attribute the pool *nearly*
has is more dangerous than one it plainly lacks, because the model will find a
plausible coarser field to put it in.

## Amended 2026-07-27 — the ladder's third rung, made explicit

The ladder above reads `country → culture_tag → (global)`. As built, a region that
reaches neither of the first two rungs yields **nothing**, not a global panel. Stating
why, since it looks like a dropped rung:

The global rung is implemented — it is what an unnamed region gets. *"Cautious
homeowners"* with no place mentioned draws from every seeded country, which is exactly
what was asked for. But *"Nigeria"* is a place we cannot serve, and answering it with
a US/JP/DE panel is the thing this ticket's last bullet forbids: **"Empty result is an
honest outcome when even the coarse tag has no seeded coverage — report it, don't
fabricate a panel."** A global panel there is a fabricated one.

So the rungs are conditioned on what was asked, not walked blindly:

| the target | rung | panel |
|---|---|---|
| names a seeded country | `country` | that country |
| names a place we can bucket | `culture_tag` | the seeded countries in that bucket, with a warning |
| names no place at all | `global` | every seeded country |
| names a place we cannot bucket | — | empty, with a warning |

## Amended 2026-07-27 — the middle rung is model-supplied, and why

The ladder's `culture_tag` rung is what serves an unseeded country, and **the tag for
such a country comes from the translator, not from code.** `COUNTRY_CULTURE_TAG` maps
only the three seeded locales, so nothing here can classify `CN` on its own. If the
model returns a null tag, China takes the bottom rung and draws nobody — with a
warning, but not the Japan panel this ticket's own worked example describes.

That is a deliberate choice, and the alternative is worse. Classifying every country
on earth needs a committed country → tag table, and the coarse vocabulary itself has
no source: [001](001-decide-persona-schema-and-seed.md) already flagged "Asian /
Western" as not a census category. A hand-authored world table would be a large
unsourced constant sitting under every fallback decision. Asking the model to bucket a
country it plainly knows, and then *showing the customer the substitution*, keeps the
judgement visible instead of burying it in a table nobody can check.

What this costs, stated plainly: the middle rung's reliability is the translator's,
not the code's. The prompt now requires a tag whenever the place is a single country,
and the live run returned `asian` for China unprompted — but one sample is not a
guarantee, and the test that exercises this rung injects the tag through a stub, so it
cannot catch a model that stops supplying one. **The bottom rung is the safe failure**:
no tag means no panel and a warning, never a wrong panel.

Worth revisiting if the country list ever becomes data rather than code — the same
trigger the `culture_tag` amendment above already identifies, since a `countries` table
would be the natural home for a sourced tag.

## Amended 2026-07-27 — where the 100–300 bound lives

The Goal says *"panel sampling: 100–300 personas"*. `select_panel` takes `size` with
no range check, and `retrieve_panel` only rejects `size < 1`.

Deliberate: the bound is a product policy and belongs with whoever decides the panel
size, which is [010](010-assemble-orchestrator-graph.md). Enforcing it inside a
retrieval function would make the mechanism refuse legitimate small draws — tests take
3, and a future segment-vs-segment comparison may want fewer. **010 owns the check**,
against the signed-off n=200 default.

## Amended 2026-07-27 — how far the seed actually reaches

`seed` reaches only a target with **no** disposition. Ranking by cosine similarity is
already determined, so every seed returns the same top-n for a dispositional target,
and that covers most of what this ticket exists to serve.

The consequence: *reproducibility* holds everywhere (one target, one panel, run after
run), but *two independent draws of one target* — the thing sample-stability wants —
is only available where nothing is being ranked. Getting it under a disposition needs a
match-then-sample step: take the top-k, then sample `size` from it. That needs a `k`,
which needs evidence, so it belongs with the map's panel-sampling fog item rather than
here. Pinned by a test so the limit is documented rather than accidental.

## What is left for [010](010-assemble-orchestrator-graph.md)

`select_panel` is not wired into `/evaluate`, which still votes `FIXED_PANEL` (5
hand-authored personas). `settings.targeting_model` is therefore unread — matching
`analyst_model`, which has been declared and unread since [012](012-build-analyst-chatbot-tools.md)
was specced. The model stays config either way (003), and the alternative is 010
adding the line back. Swapping the panel source is 010's stated content — "parse
target → retrieve + sample personas" — and it needs a DB dependency the endpoint does
not have yet. 010 also chooses the panel size; n=200 is the signed-off default.

One thing for 010 to decide rather than discover: a shortfall notice fires when fewer
personas match than were asked for, and at n=200 a thin panel changes **what the
verdict can say** — `practical_tie` needs roughly 1,100 votes at ±7 to be expressible
at all. The report must not present a 40-persona panel's verdict as a 200-persona
one's.

## Not in scope here, deliberately

- **Representativeness within a target.** With a disposition, the panel is the top-n
  by similarity, which is the *most extreme* matching personas rather than a
  representative sample of them. That is arguably right — the customer asked for
  cautious people — but it also skews the panel on attributes nobody asked about,
  since one vector carries all five traits plus demographics. The map's "panel
  sampling procedure" fog item is where this graduates; a match-then-sample variant
  needs a ratio, and a ratio needs evidence.
- **A vector index.** No HNSW/IVFFlat: at 5k rows a sequential scan over a
  hard-filtered subset is not the bottleneck. Deferred to
  [012](012-build-analyst-chatbot-tools.md), which already owns the note.
