---
title: "Demographics sampler: joint demographics per country (US/JP/DE) + typed fields + age floor"
labels: [wayfinder:task]
parent: 006-build-persona-pool
blocked_by: []
assignee: null
status: open
---

## Goal

Sample the demographic fields (age, gender, income, education, sub-national region) for the three seeded countries — **US, Japan, Germany** (001 amendment 2026-07-21) — each from its own national statistics source, drawing from the **real joint distribution** so slices are congruent by construction (not independent marginals). Add the **country/locale** grounding key + derived **culture_tag**. SQL-filterable.

Design basis: [001](001-decide-persona-schema-and-seed.md) (esp. the 2026-07-21 multi-region amendment), [006](006-build-persona-pool.md).

## The central challenge

"Sample from a census" is trivial for the US (ACS PUMS = public individual-level microdata → joint is free). The hard part is getting **comparable joint** demographics from three different national statistics systems, which may publish very different things (Germany/Japan may only expose aggregate cross-tabs, or gate microdata behind research-data-centre applications).

## Sequence (research-first — decided 2026-07-21)

1. **Data-source research pass** → `docs/research/demographic-sources.md`. ✅ *(PR #10)*
2. **Harmonization + fidelity decisions** (grill). ✅ *(see Resolved)*
3. **Schema evolution** (`backend/app/schemas.py`): added `country: Locale` + derived `culture_tag`; dropped `region`; `income` → `income_quintile`; `education` → `EducationLevel`. ✅ *(PR #11)*
4. **The sampler** — see **Sampler design** below. ⬅ *next*

## Open decisions

- **Fidelity strategy (when true microdata isn't public):** (A) microdata everywhere (may need restricted-access applications); (B) hybrid — US from PUMS, JP/DE reconstruct the joint from public cross-tabs via **iterative proportional fitting (IPF)**; (C) best-available, falling back to independent marginals where joint isn't public (retreat from 001's congruence). *Decide after the research pass.*
- **Harmonization of income/education:** per-country typed vocabularies (faithful, not cross-comparable) vs an international standard (**ISCED** for education; PPP or within-country quantiles for income). Determines how the schema types these fields.
- **Age floor** — the tracer's `ge=18` is a placeholder. Three-way trade-off, now cross-country:
  - *Market coverage* — teens (13–17) are a real audience; 18+ can't serve them.
  - *Psychometric grounding* — the 006a Big Five norms are validated on adults (D&L covers down to 16); conditioning minors extrapolates.
  - *Ethics/compliance* — simulating minors touches COPPA (<13, US) and equivalents in JP/DE; 18+ sidesteps it.
  - Whatever is chosen, update `Persona.age` in `backend/app/schemas.py`.

## Resolved (2026-07-21, post data-source research + user-supplied JP sources)

See [`docs/research/demographic-sources.md`](../docs/research/demographic-sources.md).

- **Fidelity = (B) hybrid** — the data forces it (microdata-everywhere is infeasible): **US** direct from ACS PUMS; **DE** demographics direct from **Destatis public cross-tabs** (no institutional affiliation → not IPUMS-International) + income IPF from Mikrozensus bracket cross-tabs; **JP** IPF from public e-Stat cross-tabs.
- **Harmonization:** education → **ISCED 2011** (3 levels: below_secondary / secondary / tertiary); income → **within-country quantiles** (not PPP — congruent-by-construction, and consistent with the no-cross-country-comparison stance).
- **Japan income upgraded (🔴→🟡):** individual, same-frame **就業構造基本調査 (Employment Status Survey 2022)** — collects individual 所得 + 世帯所得 jointly with age×sex×education×prefecture; corroborated by **賃金構造基本統計調査** (employees-only). Removes the household→individual bridge; Japan now ~on par with Germany.
- **Age floor = 18** (2026-07-21). Cleanest ethics/compliance posture across US/JP/DE and future-proof against the regulatory trend restricting under-18s online (e.g. Australia's under-16 social-media ban and similar pushes). Grounded (inside the D&L 16–19 band) and simplest — matches the tracer's existing `Persona.age = Field(ge=18)`, so no schema change for the floor. Documented limitation: no teen (13–17) coverage — an acceptable, increasingly regulation-aligned v1 boundary.
- **Sub-national region dropped for v1** (2026-07-21). Kanto/Kansai/Länder/US-division level is deferred under 001's "earn their place" rule: it has a small effect on votes, isn't conditioned into Big Five (decision (i)), and was the single most expensive field to type (country-dependent vocab). The **region concept that matters is Western vs Asian**, which is `culture_tag` — a deterministic function of `country` (JP→Asian, US/DE→Western), a first-class targeting key but **derived, not a stored `Persona` field**. The sampler marginalises over sub-national region (joint over age×gender×income×education per country; congruence intact). Add sub-national region later only if targeting shows it moves results.
- **Income = within-country quintiles (1–5)** (2026-07-21). `income: str` → `income_quintile: int = Field(ge=1, le=5)`. Quintiles (not deciles) — coarse but enough to target high/low income, and maps cleanly onto the bracketed public data.
- **Education = ISCED 2011 collapsed to 3 levels** (2026-07-21). `education: str` → an `EducationLevel` enum (`below_secondary` / `secondary` / `tertiary`; boundaries at high-school and university completion). Coarsened from an initial 5 — finer levels are false precision for v1's copy-engagement signal and fight the fuzziest ISCED boundaries; split later only if the manipulation check earns it.
- **New field `country: Locale`** (US/JP/DE) — the grounding key.

## Sampler design (2026-07-21 grill)

**Two stages**, so the data heterogeneity (US microdata vs DE/JP cross-tabs) is quarantined in stage 1 and the sampler on top is one uniform path.

### Stage 1 — build-joint (offline, per country)

A **general engine**, not per-country bespoke code: `(cross-tabs, seed) → (joint, fidelity descriptor)`. Produces a compact joint distribution over `age_band × gender × education × income_quintile`.

- **US** — aggregate ACS PUMS records directly (IPF degenerates to tabulation) → **exact**.
- **DE / JP / future countries** — **IPF/raking** from whatever public cross-tabs exist, seeded with the richest available demographic cross-tab (census `age×gender×education`), raking income in. IPF implemented **in-repo** (short, unit-testable against target margins; no dependency).
- **Income → quintile is computed here** (US: exact percentiles of continuous income; DE/JP: cumulative population share of income brackets), folded into the joint so stage 2 never sees raw income.
- **Fidelity is declared per dimension-pair:** `observed` (some input cross-tab contains the pair) vs `imputed_independent` (no input covers it — IPF cannot invent the correlation). One engine spans the completeness spectrum: **US exact → JP high → DE medium (edu×income may be imputed) → data-poor future country low.** **Adding a country = supply its cross-tabs; the engine emits a joint + auto-declares fidelity; no new code, no "complete data" requirement.**
- **Raw source data is NOT committed** — stage-1 scripts crunch the gigabyte sources offline into the small artifact.

### The artifact (committed)

Flat CSV per country (`backend/app/data/joint/{us,de,jp}.csv`), one row per occupied cell, columns `age_band, gender, education, income_quintile, weight` (~KB), plus provenance + the fidelity descriptor (source, date, exact-vs-IPF, observed/imputed pairs).

- **Common `age_band` scheme across all countries — the D&L bands:** `18-19, 20-29, 30-39, 40-49, 50-59, 60-69, 70-79, 80+`. Common (not per-country) for uniform/comparable tables, easy country-addition, and end-to-end consistency with Big Five conditioning (006c). Census 5-year groups nest in; US aggregates down; youngest clipped to 18.

### Stage 2 — sample (runtime, uniform, seeded)

Country-agnostic pure function `(joint table, seed, N) → N × PersonaDemographics`: weighted-pick a row ∝ `weight` → **uniform-resolve `age_band` → concrete `age`** → emit. **Fixed seed → reproducible pool** (002/007). Dev at ~200/country; full pool a later batch (006f).

### Output type

`PersonaDemographics(BaseModel)`: `country, age, gender, income_quintile, education` — typed/validated, reuses `Locale`/`EducationLevel`. **`Persona` inherits it** (`class Persona(PersonaDemographics)` + `id, interests, big_five`) so the field defs live in one place. Big Five → 006c, interests → 006d, assembly + persistence → 006f.

### Fidelity flags (carried into the 006g QC)

- **DE `edu×income`** may be `imputed_independent` if no public `income×education` cross-tab exists → declared, revisit when a better table surfaces (don't block v1).
- **Uniform-within-band** age resolution flattens the within-band age slope (worse for wide bands) — acceptable v1.
- **JP** Employment-Status-Survey income covers employed persons; reconciling with the all-population census frame (non-employed → bottom income) is a stage-1 detail.

## Data-acquisition & pipeline layout (2026-07-21 grill)

Stage 1 is **offline tooling, run rarely** (only on a data-vintage update); stage 2 is the runtime app. They're cleanly separated and share data **only through committed files, never imported code**.

### Layout

```
backend/
  app/                          # runtime (stage 2); reads CSVs with stdlib csv
    data/joint/{us,de,jp}.csv         # COMMITTED stage-1 output
    data/joint/{us,de,jp}.meta.json   # COMMITTED provenance + fidelity sidecar
  pipeline/                     # offline tooling (stage 1) — NOT imported by app/
    raw/                        # GITIGNORED: downloaded PUMS / cross-tabs
    ipf.py                      # in-repo IPF engine
    build_{us,de,jp}.py         # raw → joint
    README.md                   # exact sources, table IDs, vintages, how to re-run
```

- **`pipeline/` never imported by `app/`;** the dependency edge is one-way, through the committed CSVs only.
- **Deps isolated:** pandas/numpy live in a `pipeline` uv group, *not* runtime deps — pandas never ships to production; the app stays a thin CSV reader.
- **Storage seam:** stage 2 reads the joint through a single `load_joint(country) -> list[JointCell]` accessor, never by opening files inline — so the storage behind it (committed CSVs now → a DB later, if many countries/versions ever warrant it) is swappable in *one function*, no changes to the sampler or build scripts. (The big DB customer is the persona *pool* itself — 006f/pgvector — not these tiny input tables.)

### Acquisition = manual, documented (not automated fetch)

The pipeline runs rarely, so we **don't** maintain three brittle national-API integrations (Census keyless, e-Stat appID, Destatis registration). Instead: **manual download into gitignored `raw/`, per a precise `README.md` recipe** (exact table IDs, filters, vintages, save-as paths); build scripts read local files and never touch the network. **No API credentials to manage.** Reproducibility rests on documented pinning + the committed outputs, not live re-fetching.

- **Committed: only the derived joint CSVs + `.meta.json`** (our transformation, a few KB). **Raw is gitignored** — US PUMS is gigabytes, and committing raw government tables raises redistribution-licensing questions. (Optional later: commit a small input to `pipeline/inputs/` if a source's license clearly permits.)

### Provenance — sidecar `.meta.json` per country

Structured (so 006g QC can parse fidelity programmatically): `source`, `table_id`, `vintage`, `retrieved`, `raw_checksum`, `build` script, and the `fidelity` descriptor (`exact` bool, `observed_pairs`, `imputed_independent`). CSV stays pure data.

### Gender × income (pay gap) — fidelity ladder

Modeled (kept, for predictive accuracy — see the "keep gender" decision). The pay gap is a **hard, cross-nationally-comparable economic statistic** (measured from earnings, not self-report), so unlike Big Five means, borrowing across countries is legitimate. Fallback ladder, each tier **declared**:

1. **Full joint** `income×gender×age×education` — US (microdata), JP (Employment Status Survey).
2. **Country's own published pay-gap marginal**, post-raked — DE (Destatis Gender Pay Gap).
3. **OECD per-country** gender wage gap ([OECD indicator](https://www.oecd.org/en/data/indicators/gender-wage-gap.html)) — that country's real figure when its national cross-tab is absent.
4. **OECD average** — true last resort (broader base than any two countries, so less biased than a US+JP mean). Declared as an estimate.

v1 uses **tiers 1–2 only** (US/JP full joint, DE own marginal); tiers 3–4 are documented policy for future data-poorer countries. A single marginal captures the overall shift but not the age/education interaction — declared as `marginal-only`.

### Build order

US first (exact, no IPF — the simplest path and it validates the whole two-stage flow), then DE, then JP (IPF).

## Amendment (2026-07-22) — pivot to OECD as a single harmonized source

Supersedes the per-country national-source plan above (ACS PUMS / Destatis / e-Stat) and its per-country manual downloads. Research: [`docs/research/oecd-demographic-data.md`](../docs/research/oecd-demographic-data.md) (verified against the live OECD SDMX API).

**Why:** per-country acquisition (a separate manual download + adapter each) doesn't scale. Instead, one harmonized programmatic source queried by country code.

- **OECD SDMX REST API** (`sdmx.oecd.org/public/rest`) — **public, keyless**, one query grammar. Supplies **`age × gender × education` as direct cross-tabs**, education **native ISCED-2011** (`0T2 / 3_4 / 5T8` = our below/secondary/tertiary — the per-country education crosswalk is gone). Adding a country later = a query, not a new source.
- **Income is the accepted weak point.** The OECD IDD has **no sex and no education dimension** — income can't be crossed with demographics anywhere in OECD (or in published aggregate data generally). So income enters as a **country marginal**; `education×income` is **imputed-independent**, `gender×income` is a pay-gap-ratio tilt, `age×income` is coarse (working/retired). This is the intrinsic price of no-per-country-microdata, and it's **declared** in the fidelity descriptor. **World Bank PIP** (keyless, 160+ countries) is the income-decile + non-member fallback.
- **Supersedes:** the three per-country builders collapse into one **`build_oecd(country)`**; the PUMS `build_us.py` is removed. The `age×gender×education` block is *directly observed* (less IPF than planned); IPF/independence only attaches the income marginal.
- **Unchanged:** stage 2 — the sampler, `load_joint`, `PersonaDemographics`, the schema, and their tests all stand; only stage-1 acquisition changed.

### Age reconciliation in `combine` (2026-07-22 grill)

Three age grids don't align: our stored **D&L bands** (`18-19, 20-29, 30-39, 40-49, 50-59, 60-69, 70-79, 80+`), OECD **population** (5-year: `Y15T19 … Y_GE85`), and OECD **education** (`Y25T34, Y35T44, Y45T54, Y55T64` — 25-64 only, offset from ours).

- **5-year lattice blend.** Reconcile on the 5-year population grid, not the D&L bands directly: every 5-year group nests *entirely* inside one education band (`Y25T29, Y30T34 ⊂ Y25T34`; etc.), so there's no arbitrary tie-break. Each 5-year cell takes its containing education band's `P(edu | age, sex)`, weighted by that group's population; cells are then summed up into D&L bands — the D&L education mix falls out as the population-weighted blend.
- **Gaps → nearest observed band, declared imputed.** Education is age-*ordered* (young = not-yet-completed; old = lower-tertiary cohort), so the adjacent band is a better prior than a pooled grand mean. Groups `<25` (18-24) borrow `Y25T34`; groups `≥65` borrow `Y55T64`. Flagged imputed in the fidelity descriptor. (A country missing a *whole* dimension is the separate IPF/pooled-borrow case, not this.)
- **`18-19` sub-band.** No clean count exists (population's finest is `Y15T19`, which includes 15-17 below our floor). Take the uniform fraction (2/5 of `Y15T19`), declared.
