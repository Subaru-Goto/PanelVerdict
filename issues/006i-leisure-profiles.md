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
  Per-category participation booleans as SQL columns (filterable — same rationale as 006f D2's
  hard fields and the five Big Five columns). Plus one
  `summary_embedding vector(1536)` column. Net schema is *simpler* than today:
  one vector per persona instead of one per interest, one table instead of two.
- **D2 — Five categories every survey publishes: `tv_media`, `socializing`,
  `sports_exercise`, `volunteering`, `hobbies_and_games`.** Japan's diary is the
  coarsest of the three, so it sets the granularity and the others aggregate up
  to meet it. Every country fills every category; no country carries a
  partly-empty table or a category of its own.

  *This replaces two earlier attempts, both over-built.* First a set of 11–13
  categories harmonized to the finest available taxonomy, then a **union**
  vocabulary where each country filled what it published and declared the rest
  in `{cc}.meta.json`, enforced by a coverage check. Both preserved German and
  US granularity that the persona summary was never going to use, and the union
  version needed a Japan-only `hobbies_amusements` category to avoid one name
  meaning two things. The five-category set makes all of that machinery
  unnecessary.

  Coarsening **improved** comparability rather than costing it. Folding print
  media into `tv_media` (`AC81_X_812` beside TV and radio) and walking into
  `sports_exercise` (`AC611` beside `AC6_X_611`) makes Germany's definitions
  match Japan's exactly, removing two of the three scope differences the union
  design had to declare. `rest_relaxation` was dropped with them: it was the
  widest gap in the table — Japan's broad 休養・くつろぎ at 68.1% of men against
  Eurostat's narrow "Resting - time out" at 18.5%, mostly definitional — and
  resting is not a hobby.

  Two scope differences survive and are declared in the country's `.meta.json`
  rather than smoothed: JP `socializing` is 交際・付き合い, which excludes
  conversation at home where Eurostat's includes it; and US `tv_media` is
  television only, because ATUS publishes one undifferentiated "Reading for
  personal interest" row that cannot be split between print media and books.
- **D2b — Rates only, no durations.** The pool needs to know *whether* someone
  is into something, not for how long. Minutes would be rendered as text
  ("175 minutes a day") that is not comparable between surveys — the JP/DE
  resting gap is the proof — and drawing a plausible duration needs a spread
  model no survey supports (it was already deferred to v2 as unsourced). One
  number per cell: the participation rate.
- **D3 — Generative model, per persona, fully sourced:** for each category,
  `participate ~ Bernoulli(participation_rate[country, gender, age_band])`.
  That is the whole model — no second draw, no spread. Deterministic off the
  existing per-slot RNG, so dev-subset-is-a-prefix and resume both still hold.

  **Leisure is not a personality signal, and must never be read as one.** Big
  Five is sampled independently, from published norms by age and gender
  (`bigfive.py`); leisure is a parallel descriptive layer, and the two are drawn
  from separate RNG streams with no correlation between them. That separation is
  deliberate, because time-use largely measures *constraint*, not disposition:
  Japanese men work 267 population-minutes a day against Germany's 172 and are
  12pp likelier to be working at all, so their higher resting time is mostly what
  is left after a longer working day. Reading minutes as traits would label a
  whole country lethargic for working longer, and would call Germans altruistic
  because `volunteering` is 14% there against Japan's 1.8% — an institutional
  difference, not a moral one.

  The honest cost of that stance: a high-openness persona currently draws the
  same leisure distribution as a low-openness one, though real openness does
  correlate with reading and arts. Conditioning leisure on traits would need
  per-country time-use × personality crosstabs, and none of the three surveys
  publishes one — so the only way to add the correlation is to invent it, which
  is exactly what sank the hobby banks. It stays independent until someone finds
  a published crosstab. What leisure buys instead is concreteness for the D6
  summary embedding, country realism in the vote prompt, and a real external
  validation target for 006g.
- **D4 — Conditioning: country × gender × age band**, on the bands
  `15-24 / 25-34 / 35-44 / 45-54 / 55-64 / 65+`. Eurostat publishes all six
  directly; Japan publishes four ready-made and the two middle bands are the
  population-weighted mean of its five-year groups, weighted on the populations
  the table prints beside them; ATUS publishes no rates by age at all, so the US
  will use the gender-only rung of D8 (slice 1b). Age is what the conditioning buys — Japanese
  men's `tv_media` runs 0.23 at 15-24 to 0.88 at 65+, and `hobbies_and_games`
  falls 0.38 to 0.20 across working age before recovering at retirement.
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

  **Open question for slice 4 — absolute minutes or within-country bands?** D2's
  per-country coverage argument rests on personas being compared only within a
  country. Nothing enforces that: there is no selection layer yet (007), and if
  an unspecified market means "draw from the whole pool", one panel can mix all
  three countries. Absolute minutes would then leak survey-coding differences
  into persona text as if they were behaviour — a Japanese persona reading as
  idle next to a German one purely because 休養・くつろぎ is a broader code than
  `AC531`. The precedent for the fix is already in `panel.py`: `_income_band`
  renders income as a within-country band ("the lower income range") precisely
  because quintiles are not comparable across countries. Leisure most likely
  wants the same treatment — "relaxes more than most people where they live"
  rather than "175 minutes a day". Decide after eyeballing real personas; the
  data layer stores sourced absolute values either way, so this is purely a
  rendering choice and nothing upstream has to change.
- **D8 — Missing cells fall back to the coarsest published prior, never to a
  guess.** Surveys differ in what they cross: Eurostat and e-Stat publish
  activity by gender *and* age, ATUS by sex alone (its age tables are
  unpublished, available only by e-mailing BLS). So `_cell_rate` walks a ladder
  — gender×age, then the gender's own all-ages figure, then the all-gender band,
  then the national total — and takes the first the survey actually publishes.
  The level used is declared in `{cc}.meta.json`, so a country conditioned on
  less than both axes says so. Germany and Japan currently need no fallback; the
  US will use the gender-only rung.

  **Extending the ladder across countries is the next rung, not this slice's
  work.** For a country with no time-use survey at all, the fallback should be
  the mean of countries sharing its cultural cluster, then the global mean. Two
  conditions before building it: it belongs in slice 2's loader (the pipeline
  builds one country from one survey and should stay that way), and the
  clustering must come from a **published** source — the Inglehart–Welzel /
  World Values Survey cultural zones put DE in Protestant Europe, JP in
  Confucian, US in English-Speaking — never from our own judgement about which
  countries resemble each other. Until a country without data actually exists,
  building it would be generality with nothing to validate against.
- **D7 — Anti-stereotype QC changes purpose, doesn't disappear.** Cosine
  dispersion over invented interest text is meaningless once interests are
  code-sampled. The stronger check belongs to 006g: **realized pool
  distributions vs the published survey numbers** per country/gender.

## Slices (one PR each)

1. `pipeline/build_leisure.py` + the harmonized category set + **Germany**
   (`de.csv`, Eurostat JSON API). Split per country while building, because each
   survey is a different extraction problem with its own gaps to declare.
1b. **US** (`us.csv`) — ATUS 2025 Table A-1, transcribed from the published PDF
   (BLS serves no machine-readable copy and blocks scripted clients). Publishes
   rates by sex but not by age, so every band uses the gender-only rung of D8.
1c. **Japan** (`jp.csv`) — 社会生活基本調査 2021 table 1-1, downloaded from e-Stat
   without an application ID. Publishes participation rates by sex and by
   five-year age group, so nothing is derived beyond the two combined bands.
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

- **Split `hobbies_and_games` and `sports_exercise` into finer categories,
  sampled as distributions.** The coarse five are what all three surveys share
  *on a diary-day basis*; two of the three already publish the finer split, so
  this is a data-availability problem, not a modelling one. ATUS Table A-1
  separates playing games (18.5% of men), computer use for leisure (14.5%),
  reading for personal interest (13.4%) and arts and entertainment (1.9%) — the
  four rows this slice unions into one. Eurostat separates the same four
  (`AC733-735`, `AC72`, `AC812`, `AC711_712...`) plus walking from other sport
  (`AC611` vs `AC6_X_611`). Japan is the blocker: its diary has only 趣味・娯楽,
  and the 60+ named activities it does publish (video games 42.9%, gardening
  26.0%) are **past-year** rates, so they cannot share a column with diary-day
  rates. Options when this is picked up: carry finer categories only for
  countries that publish them and let the ladder (D8) serve Japan the coarse
  parent, or add a second past-year layer with its own semantics. The first fits
  D8 as it stands.
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
