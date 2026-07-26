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
  and the five trait levels. `app/panel.py` already owns this rendering
  (`_TRAIT_PHRASES` via `bucketize`, `_income_band` for the within-country band)
  — the summary must reuse it rather than grow a second copy that can drift.
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
- **D5 — Open, and the reason to build the ablation harness anyway: does any
  persona attribute move a vote?** Nothing in this project has tested it. Fix a
  set of headline pairs and run the same personas with demographics only, then
  + Big Five, and compare verdict distributions. If Big Five doesn't move them,
  the problem is the prompt, not the attribute set, and that finding outranks
  every design decision in this ticket. Cheap to run; run it before adding any
  further persona field.

## Slices (one PR each)

1. **Summary template + tests.** Pure function `persona_summary(persona) -> str`
   reusing `panel.py`'s trait and income rendering. No schema change yet.
2. **Schema + persistence.** Add `summary_embedding`, drop the `interests`
   table, update the seed script; embedding call moves to assembly.
3. **Deletion.** Remove the interest-synthesis path in `interests.py`,
   `stereotype_audit.py`, the hobby CSVs and their tests; narrow
   `plausibility.py` to demographic/trait coherence or retire it; drop the
   `interests` line and the hand-authored example personas' interest lists in
   `panel.py`. Last, so nothing breaks mid-way.
4. **Ablation harness (D5).** Verdict distributions across attribute sets over a
   fixed headline pair set.

## Knock-on

- **006d/006e** — superseded, not "done": no LLM-generated interest text remains
  for their validators, audit or judge to act on.
- **006g** — the interest frequency/diversity panel and its stereotype flags go;
  what remains is demographics vs OECD and Big Five vs the 006a priors.
- **007** — unchanged in mechanism, narrowed in coverage (D4).
- **012** — the pgvector index targets `personas.summary_embedding`; the
  `CREATE INDEX CONCURRENTLY` / `autocommit_block` note there still applies, and
  the "mean-pool vs per-interest rows" question it raises is now moot.
