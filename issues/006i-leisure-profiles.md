---
title: "Leisure profiles: replace generated interests with surveyed time-use"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: [006f-persistence]
supersedes: [006h-menu-mode-interests]
assignee: null
status: open
---

## Goal

Drop LLM-generated hobby text. A persona's leisure life becomes a **profile of
surveyed time-use categories** sampled from national time-use surveys, and
semantic targeting moves onto a **templated persona-summary embedding**.

Every number in the persona pool then traces to a citable table, and the machinery
that existed only to police LLM-invented interests goes away.

Data basis: [`docs/research/leisure-time-use-sources.md`](../docs/research/leisure-time-use-sources.md).
Supersedes [006h](006h-menu-mode-interests.md); reverts most of
[006d](006d-interests-synthesis.md).

## Why

Three successive interest designs failed on measurement, each in the same way —
the model's style prior beat every attempt to steer its output distribution:

1. Free generation (006d) → manufactured compounds, per-demographic templates.
2. Rotating prompt examples (PR #29) → measured **echo 0.03 / in-bank 0.26**;
   `homebrewing` at ~10% of personas, `bonsai` ~6% (real rates <1%); zero
   mainstream hobbies in the top-20.
3. Menu-mode (006h) → would have worked mechanically, but required **~430
   invented weights** plus an invented interest-count distribution. Rejected:
   unmaintainable, and the numbers were fabrication dressed as data.

The root problem is that an open hobby vocabulary has no ground truth we can
obtain per country. Time-use categories do — measured, gendered, age-banded,
published, and re-pullable. **~10 sourced rows per country instead of ~140
invented ones.**

## Design

- **D1 — Storage: wide columns on `personas`, `interests` table dropped.**
  Per-category minutes as SQL columns (filterable — same rationale as 006f D2's
  hard fields and the five Big Five columns). Plus one
  `summary_embedding vector(1536)` column. Net schema is *simpler* than today:
  one vector per persona instead of one per interest, one table instead of two.
- **D2 — Harmonized category set (~8–10)** mapped across the three surveys'
  differing taxonomies: tv_media, socializing, games, sports_exercise,
  outdoor_walking, reading, arts_crafts_music, going_out, computer_leisure,
  gardening_pets. Harmonization is the main data-engineering task; the mapping
  table in the research doc §5 is the starting point and belongs in the CSV as
  a cited `source` column per row.
- **D3 — Generative model, per persona, fully sourced:** for each category,
  `participate ~ Bernoulli(participation_rate[country, gender])`, and if
  participating, minutes drawn around the **participant mean**
  (`population_mean / participation_rate` — arithmetic from published columns;
  Eurostat publishes `PTP_TIME` directly). Deterministic off the existing
  per-slot RNG, so dev-subset-is-a-prefix and resume both still hold.
- **D4 — Conditioning: country × gender now, age where published.** All three
  surveys give gender splits; Eurostat `tus_20age` gives 16 age bands for DE.
  Age conditioning lands per country as the data allows, not uniformly.
  Demographic conditioning is now *measured* rather than model judgment — the
  requirement that killed three interest designs.
- **D5 — Pipeline mirrors `build_oecd`:** new `pipeline/build_leisure.py` with an
  injectable `fetch` callable (testable without network), writing committed
  `app/data/leisure/{us,jp,de}.csv`, and declaring imputations the way
  `BuildResult.imputations` already does. Access is asymmetric and that is
  recorded, not hidden: Eurostat is a clean JSON API; ATUS needs the archive
  mirror or microdata (bls.gov 403s scripts); JP needs e-Stat detail tables.
  Manually extracted rows are allowed **only** with a `source` citation.
- **D6 — Semantic targeting preserved (007's vector half).** Template a prose
  persona summary from sourced facts — *"35-year-old man in Japan, university
  degree, high openness; spends most free time on TV and video games, some
  cycling, rarely socializes"* — and embed that. Hybrid retrieval stays as 007
  specifies (SQL for hard attributes, vector for fuzzy intent), and is richer
  than hobby-only vectors because demographics, traits, and leisure share one
  semantic space. No LLM in the loop: the summary is a deterministic template.
- **D7 — Anti-stereotype QC changes purpose, doesn't disappear.** Cosine
  dispersion over invented interest text is meaningless once interests are
  code-sampled. The stronger check belongs to 006g: **realized pool
  distributions vs the published survey numbers** per country/gender.

## Slices (one PR each)

1. `pipeline/build_leisure.py` + committed per-country CSVs (harmonized
   categories, participation rate + participant mean by gender, `source` per row).
2. `app/leisure.py`: `sample_leisure_profile(country, gender, rng)`. Pure logic, TDD.
3. Schema + assembly + persistence: add leisure columns, drop `interests`, wire
   into `assemble_persona`.
4. Persona summary template + embedding column; update the panel-vote rendering
   to describe leisure instead of listing interests.
5. Deletion PR (last, so nothing breaks mid-way): remove `hobbies.py`,
   `echo_audit.py`, `stereotype_audit.py`, the interest-synthesis path in
   `interests.py`, the three hobby CSVs, and their tests; narrow
   `plausibility.py` to demographic/trait coherence or retire it.

## Knock-on effects on other tickets

- **006d/006e** — interest synthesis and its injection screen are moot (no
  LLM-generated interest text remains). Record as superseded, not "done".
- **006g** — interest frequency/diversity panels become *leisure distribution vs
  survey targets*, which is a real external validation the pool never had.
- **007** — unchanged in design; the fuzzy half now runs on the persona summary.
- **012** — vector index moves to `personas.summary_embedding` (one per persona,
  not per interest); the `CREATE INDEX CONCURRENTLY` note there still applies.

## Deferred to v2 (recorded, not lost)

- **Survey-sourced named activities** where the data exists: Japan already
  publishes 60+ named rates (walking 44.3%, video games 42.9%, gardening 26.0%,
  karaoke 13.5%, baseball 6.3%); US via SPPA/USFWS; DE sports via DOSB
  memberships. Legitimate as *data*, never as invention — per country, as
  available.
- Age conditioning for countries where only gender is published now.
- Within-category spread modelling if flat participant-mean jitter reads
  unrealistically in the eyeball.
- JP 2021 COVID distortion (karaoke −17pts, travel, live events): use 2016
  comparators when a category looks depressed.
