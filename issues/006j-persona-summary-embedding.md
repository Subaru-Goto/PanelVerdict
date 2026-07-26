---
title: "Persona summary embedding: drop interests, embed demographics + Big Five"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006f-persistence]
supersedes: [006d-interests-synthesis, 006i-leisure-profiles]
assignee: null
status: open
---

## Goal

A persona stops carrying an `interests` list. Fuzzy targeting moves onto a
**templated persona summary embedding** built from the fields we can actually
ground — demographics and Big Five — and the machinery that existed only to
police LLM-invented interest text goes away.

This is what [007](007-build-targeting-query-translation.md)'s vector half runs
on, so it blocks the RAG requirement.

## Why

Four designs tried to give a persona hobbies. Free generation, rotating prompt
examples and menu-mode all failed on the same thing: an open hobby vocabulary has
no ground truth per country, so either the model's style prior sets the
distribution (`homebrewing` at ~10% of personas against a real rate under 1%) or
we invent the weights ourselves (~430 of them). Leisure profiles from national
time-use surveys ([006i](006i-leisure-profiles.md)) *did* solve the grounding
problem — every number traced to a published cell — and were closed anyway,
because each country cost a bespoke extraction and no test showed the field
changes a verdict.

The conclusion those four attempts converge on: **the hobby field was never the
mechanism.** What the research supports is Big Five conditioning LLM decisions.
So the persona keeps what is grounded and evidenced, and drops what is neither.

The side effect is the largest simplification in 006 so far. `Persona.interests`
is `min_length=1`, so `assemble_persona` *must* call the LLM, retry it, and skip
personas whose generation fails — `InvalidInterests`, the `on_failure` callback
and the regeneration path all exist to police that one field. Without it **pool
assembly is pure sampling: deterministic, LLM-free, and the only model call
anywhere in the pool build is the embedding.**

## Design

- **D1 — The summary is a deterministic template, no LLM.** Same facts the vote
  prompt already renders, in prose: country, age, gender, education, income band,
  and the five trait levels. `app/panel.py` owns that rendering today
  (`_TRAIT_PHRASES` via `bucketize`, `_EDUCATION_PHRASE`, `_income_band`).

  **One renderer, two voices.** `panel.py`'s phrases are second-person ("your own
  company"), which reads wrong in text describing a person *to a retriever*, so
  the renderer takes the grammatical person as a parameter rather than growing a
  second phrase table. Note there is *already* a second copy to remove:
  `app/interests.py` carries `_income_desc` and `_trait_levels`, built for the
  synthesis prompt. Slice 3 deletes it; nothing new should be written against it.

  Why one table matters beyond tidiness: **the persona retrieval returns must be
  described exactly as the persona that votes.** If the summary says something
  the vote prompt doesn't, retrieval promises a panel the panel doesn't deliver.
- **D1b — Five trait levels, not three, and the vote prompt moves with it.**
  `bucketize` renders three levels, so `openness = 0.51` and `openness = 2.3`
  produce identical text. Two consequences, and the second is the more serious:

  1. *Retrieval is quantized.* 5 traits × 3 levels = 243 possible disposition
     texts, so in a 5k pool ~20 personas share a cell and are indistinguishable
     to cosine — the graded ranking the vector exists for cannot order within a
     cell. Five levels gives 3,125 cells, roughly one persona each.
  2. *The vote prompt is already throwing away the sampling.* 006c samples
     correlated continuous z-scores from a measured Σ — the entire point of that
     ticket — and `render_persona_prompt` then collapses them to three buckets,
     so a z of 2.3 and a z of 0.51 receive identical voting instructions. This is
     a defect in the voting path that only became visible once retrieval and
     rendering were considered together.

  Cutoffs are standard-normal quantiles, the same derivation behind today's ±0.5
  and its "~31/38/31%" comment — **derived, not invented**:

  | level | cutoff | share of a normal population |
  |---|---|---|
  | very low | `z < -1.5` | 6.7% |
  | low | `-1.5 ≤ z < -0.5` | 24.2% |
  | medium | `-0.5 ≤ z ≤ 0.5` | 38.3% |
  | high | `0.5 < z ≤ 1.5` | 24.2% |
  | very high | `z > 1.5` | 6.7% |

  The z-score stays the source of truth and only the rendering gets finer, which
  is what `TraitLevel`'s docstring already reserves the right to change. Touches
  `TraitLevel`, `bucketize`, `_LEVEL_SCORE`/`bigfive_from_levels`, `_TRAIT_PHRASES`
  (25 phrases instead of 15) and `FIXED_PANEL`.
- **D1c — Retrieval split: hard attributes to SQL, dispositions to the vector,
  and Big Five is never a SQL filter.** 006 already decided Big Five is a
  "behavior-shaper, prompt-rendered (**not a targeting filter**)", and that holds
  here for a second reason: a translator emitting `conscientiousness > 0.5` would
  be inventing a cutoff, and a boolean conjunction of five guessed thresholds
  returns 4,000 rows or zero. Ranking degrades gracefully; filtering doesn't.
  Panels need the best 200, not a yes/no.

  **Recorded because it is the interesting trade in this design:** a persona's
  fuzzy attributes are five exact numbers, so the technically better retrieval is
  to skip text entirely — store the z-scores as a `vector(5)` and rank by
  distance from an LLM-emitted target direction (`{N:+1, C:+1, O:-1}`). Same
  hybrid shape, same pgvector operators, no embedding model, and nothing
  quantized. We are not doing that: 007 specifies an embedding query and the
  requirement is the constraint. But the text embedding is a re-encoding of five
  numbers and should be understood as one — which is exactly why D1b's
  finer rendering is worth the churn, since it is the only lever on how much of
  those five numbers survives the round trip.
- **D2 — Storage: one `summary_embedding vector(1536)` on `personas`; the
  `interests` table is dropped.** Net schema is simpler than today: one vector
  per persona instead of one per interest, one table instead of two. Keeps
  006f D2's rationale — hard attributes stay SQL-filterable columns, only the
  fuzzy half is a vector.
- **D3 — Income and any other within-country rank stay rendered as bands.**
  `_income_band` exists because quintiles are not comparable across countries;
  the summary embeds the same text a cross-country panel would read, so it
  inherits that treatment rather than embedding a raw quintile number.
- **D4 — Coverage narrows, and 007 has to say so.** Retrieval can serve
  dispositional and demographic targets; it cannot serve activity targets
  ("outdoorsy people") because no activity field exists. That is a coverage
  limit to surface the way 007's region ladder already surfaces fallbacks —
  never a silent empty result.
- **D5 — Vote reasons are not a vector store, and RAG does not need them to be.**
  Tempting, since they are the one genuinely unstructured text this system
  produces — but a 200-persona panel yields ~200 reasons ≈ 8k tokens, which fits
  in a prompt. Retrieval over a corpus you can simply pass in full is
  over-engineering with a recall risk attached. The pool is the corpus that
  actually needs retrieval: 5,000 summaries ≈ 350k tokens, so selecting ~200 of
  them by natural-language description *is* the RAG requirement, in the strict
  sense of supplying a model with information it doesn't have. Revisit when test
  *history* exists (50 tests ≈ 400k tokens of reasons) — that belongs to 012.

  Also worth knowing before over-building: at 5k personas nothing needs a vector
  index for speed (5,000 × 1536 floats is 30 MB; brute-force cosine is
  milliseconds). pgvector is justified because the personas already live in
  Postgres, because it scales, and because it is required — not by search
  latency. **Votes are not persisted at all today** (`VoteRecord` exists,
  `persistence.py` writes only personas and interests); 008/011 need that closed
  regardless of this ticket.
- **D6 — No migrations: drop and reseed.** `schema.sql` is `CREATE TABLE IF NOT
  EXISTS` only and 006f never introduced Alembic, though 012 assumes it exists.
  It isn't needed here, and the reason is a property this ticket *creates*: once
  interests are gone the entire pool is a pure function of `master_seed`, so the
  database is a cache, not a system of record — dropping and reseeding
  reproduces it byte for byte. Introduce migrations when there is data that
  cannot be regenerated (votes and test results, once persisted), and correct
  012's assumption in the same PR.
- **D7 — Open, and the reason to build the ablation harness anyway: does any
  persona attribute move a vote?** Nothing in this project has tested it. Fix a
  set of headline pairs and run the same personas with demographics only, then
  + Big Five at three levels, then + Big Five at five levels, and compare
  verdict distributions. If Big Five doesn't move them, the problem is the prompt
  and no attribute set fixes it — a finding that outranks every design decision
  in this ticket. It also settles D1b's open assumption, that a model votes
  differently given "extremely organized" versus "organized". Cheap to run; run
  it before adding any further persona field.

## Slices (one PR each)

Ordered so nothing is broken between PRs. The hazard to avoid: `qc.py` does
`FROM personas p JOIN interests i`, rebuilds `Persona(interests=…)` and imports
`stereotype_audit`, and `seed.py` calls `run_qc` — so dropping the table or
deleting the audit module without touching `qc.py` breaks the seed run.

1. **Renderer: five levels, one table, two voices** (D1, D1b). `TraitLevel`
   gains very-low/very-high, `bucketize` gains the ±1.5 cutoffs,
   `_TRAIT_PHRASES` grows to 25 phrases, the renderer takes grammatical person,
   and `persona_summary(persona) -> str` lands beside `render_persona_prompt`.
   Updates `FIXED_PANEL` and `bigfive_from_levels`/`_LEVEL_SCORE`. Pure logic,
   TDD, no schema change — and it is independently valuable, since it fixes the
   vote prompt's quantization whatever happens to the rest of this ticket.
2. **Interests out, end to end.** `Persona.interests` removed;
   `assemble_persona` stops calling the LLM (`InvalidInterests`, the retry loop,
   `on_failure`, `AssembledPersona.interest_vectors`, `seed.py`'s failure
   counter and `settings.interest_model` go with it); `schema.sql` drops the
   `interests` table and adds `summary_embedding vector(1536)`;
   `persist_persona` writes one row and one vector; `qc.py` loses the interest
   panel, the JOIN and the `stereotype_audit` import; `panel.py` drops the
   interests sentence and the hand-authored panel's interest lists;
   `tests/factories.py` and its consumers (`test_vote`, `test_panel`,
   `test_persistence`, `test_qc`) follow. Drop-and-reseed per D6.

   This is the slice that delivers the LLM-free pool, and it is large because
   `interests` is load-bearing in seven modules — split it further while writing
   if the diff outgrows a sitting.
3. **Delete what slice 2 orphaned.** `interests.py`'s synthesis path (keeping
   the `InterestLLM`/`Embedder` protocols the embedding still needs),
   `content_checks.screen_interests`, `stereotype_audit.py`; narrow
   `plausibility.py` to demographic/trait coherence or retire it. Pure deletion,
   nothing referencing it by then.
4. **Ablation harness (D7).** Verdict distributions across attribute sets over a
   fixed headline-pair set.

Retrieval itself is **not** in this ticket — 007 owns query translation and the
SQL/vector split (D1c). 006j only guarantees the column and the text.

## Knock-on

- **006d/006e** — superseded, not "done": no LLM-generated interest text remains
  for their validators, audit or judge to act on.
- **006g** — the interest frequency/diversity panel and its stereotype flags go;
  what remains is demographics vs OECD and Big Five vs the 006a priors.
- **007** — unchanged in mechanism, narrowed in coverage (D4).
- **012** — the pgvector index targets `personas.summary_embedding`; the
  `CREATE INDEX CONCURRENTLY` / `autocommit_block` note there still applies, and
  the "mean-pool vs per-interest rows" question it raises is now moot.
