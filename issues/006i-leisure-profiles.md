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
- **D2 — Category set is a *union* across surveys, with declared per-country
  coverage.** tv_media, socializing, games, sports_exercise, outdoor_walking,
  reading, arts_hobbies, going_out, computer_leisure, gardening_pets,
  volunteering, hobbies_amusements. The mapping is the main data-engineering
  task; the research doc §5 table is the starting point and each row cites its
  source. (Amended while building slice 1: `volunteering` added — published for
  DE and US; `arts_crafts_music` renamed `arts_hobbies` because the Eurostat
  aggregate excludes handicrafts.)

  **Amended again in slice 1c, once Japan's actual taxonomy was in hand.** The
  original plan was to harmonize down to the coarsest national taxonomy. Japan's
  diary turns out to publish only 5 leisure activities that map onto this set,
  with one "Hobbies and amusements" bucket covering games, books, computer use,
  arts and gardening at once — so harmonizing down would have collapsed Germany's
  and the US's finer data into a blob that carries almost no signal for headline
  voting, which is the whole point of the profile. Instead each country fills
  what its own survey publishes and declares the rest in `{cc}.meta.json`. A
  category is therefore never reported under a name meaning something materially
  different; it just isn't present everywhere. `hobbies_amusements` exists for
  Japan's coarse bucket precisely so it is *not* reported under `arts_hobbies`,
  which would be the same name meaning two different things. The build fails if
  a category is neither mapped nor declared unsupported, so adding an enum member
  cannot silently shorten a country's table.

  Two published Japanese activities are deliberately left unmapped rather than
  forgotten, and say so in `jp.meta.json`: 休養・くつろぎ (rest and relaxation,
  68.1% of men for 175 min — second only to `tv_media`) and 学習・自己啓発・訓練
  (9.1%). Resting is downtime rather than an interest and Eurostat files it under
  personal care, so neither would carry signal a headline vote could use. Each
  country's builder must declare published-but-unmapped activities the same way.

  This is sound because **personas are only ever compared within a country** —
  a US panel is scored against US personas, and the profile is consumed as a
  templated summary and its embedding (D6), never as a cross-country numeric
  join. Cross-country leisure comparison is the one thing this forfeits, and
  nothing in PanelVerdict asks for it. Scope differences that survive the
  mapping are declared rather than hidden: JP `sports_exercise` includes walking
  (Germany reports it separately), JP `socializing` is 交際・付き合い, which
  excludes conversation at home where Eurostat's includes it, and JP `tv_media`
  counts newspapers and magazines that Germany files under `reading`.
- **D3 — Generative model, per persona, fully sourced:** for each category,
  `participate ~ Bernoulli(participation_rate[country, gender])`, and if
  participating, minutes drawn around the **participant mean** — read from the
  published `PTP_TIME` cell wherever one exists, and only derived
  (`population_mean / participation_rate`) for aggregated categories that have
  no published union. Deterministic off the existing
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
  recorded, not hidden: Eurostat is a clean JSON API; e-Stat serves table 1-1 as
  a spreadsheet with no application ID (its CSV/JSON endpoints need one, its
  file download does not); ATUS needs the archive mirror or microdata (bls.gov
  403s scripts). Manually extracted rows are allowed **only** with a `source`
  citation.
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

1. `pipeline/build_leisure.py` + the harmonized category set + **Germany**
   (`de.csv`, Eurostat JSON API). Split per country while building, because each
   survey is a different extraction problem with its own gaps to declare.
1b. **US** (`us.csv`) — ATUS 2024 Table A-1 via the archive mirror; the doc's
   §1 rates are ungendered, so the by-sex columns need re-extracting.
1c. **Japan** (`jp.csv`) — 社会生活基本調査 2021 table 1-1, downloaded from e-Stat
   without an application ID. Publishes all three metrics by sex, so nothing is
   derived; fills 5 of the 12 categories and declares the other 7 (see D2).
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
  available. This is also the route that would recover what Japan's diary
  taxonomy loses (D2): the 生活行動 tables name video games and gardening
  separately, they are simply past-year rates rather than diary-day rates, so
  they cannot be mixed into the same columns without a units error.
- Age conditioning **everywhere, including DE** where 16 bands are published:
  slice 1 pins `age=TOTAL` and declares that in `de.meta.json`. Adding it
  multiplies the table by the band count and complicates the sampler, so it
  waits for a measured need.
- Within-category spread modelling if flat participant-mean jitter reads
  unrealistically in the eyeball.
- JP 2021 COVID distortion (karaoke −17pts, travel, live events): use 2016
  comparators when a category looks depressed.
