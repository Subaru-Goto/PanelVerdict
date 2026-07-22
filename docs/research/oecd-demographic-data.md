# OECD as a single harmonized source for the joint demographic distribution (age × gender × education × income) — research for the persona-pool pivot

*Date: 2026-07-22 · Method: primary-source verification against the live OECD SDMX REST API (`sdmx.oecd.org/public/rest`), OECD Data Explorer dataset pages, and OECD API documentation. **Every availability/granularity claim below was checked by actually issuing the API query and inspecting the returned data structure / observations on the date noted — not asserted from memory.** Feeds the pivot away from per-country national sources (ACS PUMS / Destatis / e-Stat, see `demographic-sources.md`) toward one harmonized programmatic source. Scope: US, Japan, Germany now; more OECD members later.*

> **Status: verdict + verified access map — read the confidence flags and the joint-granularity matrix.** Headline: **OECD is a strong single source for the DEMOGRAPHIC three-way (age × gender × education), all keyless via one API, education already native ISCED-2011.** It is a **weak** source for anything crossing **income with sex or education**: the OECD Income Distribution Database (IDD) breaks income down **by age only** (working-age / retirement / total) — it carries **no sex dimension and no education dimension at all**. So `education × income`, `age×5yr × income` and a true `gender × income` joint are **NOT observable** in OECD and must be IMPUTED (independence) or borrowed. `gender × income` is available only as a **summary pay-gap ratio** (separate Earnings Distribution Database), not a joint distribution. Details, exact dataflow IDs, and the fallback (World Bank PIP) below.

---

## TL;DR — what the OECD API supplies per dimension

| Dimension | OECD dataflow (verified) | US / JP / DE | Granularity | Cross-tabbed with? |
|---|---|---|---|---|
| **Population by age × sex** | `DSD_POPULATION@DF_POP_HIST` (agency `OECD.ELS.SAE`) | ✅ all three | **5-year age bands** (Y0T4…Y_GE85), F/M/_T | age × sex is a **direct cross-tab** |
| **Educational attainment by age × sex** | `DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA` (agency `OECD.EDU.IMEP`) | ✅ all three | **broad age groups** (25-34, 25-64, 45-54, …; NOT 5-year over full range), F/M, **native ISCED-2011** | age × sex × ISCED is a **direct three-way cross-tab** (reported as % within each sex×age cell) |
| **Income distribution** | `DSD_WISE_IDD@DF_IDD` (agency `OECD.WISE.INE`, the OECD **IDD**) | ✅ all three | Gini, decile ratios (P90/P10 = `D9_1`, `D5_1`), quintile ratio, Palma, mean/median disposable income | **age only** (18-65 / >65 / total). **NO sex dim. NO education dim.** |
| **Gender × income (pay gap)** | Earnings Distribution Database / Employment DB (gender wage gap indicator) | ✅ all three | median-earnings gap **ratio** | a single **summary statistic**, not a joint income distribution |

**API access model:** public **keyless** SDMX REST API at `https://sdmx.oecd.org/public/rest/…`; CSV/JSON/XML; **60 data downloads per hour** per client (raised from 20); `lastNObservations`/`firstNObservations` are blocked. One base URL, one query grammar, all dataflows.

---

## 1. API reality — verified keyless, one grammar for all dataflows ✅

**There is a single public API: the OECD Data Explorer / SDMX REST API.** Base: `https://sdmx.oecd.org/public/rest`. It is **keyless** — no registration, no token, just accept the Terms & Conditions. Confirmed by issuing live queries below (they returned data, not an auth error).

- API landing / docs (OECD): `https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html` (403 to automated fetch; human-viewable), FAQ `…/2024/09/OECD-DE-FAQ.html`, **API best practices** `…/2024/11/Api-best-practices-and-recommendations.html` (checked 2026-07-22)
- SDMX-JSON documentation: `https://data.oecd.org/api/sdmx-json-documentation/` (checked 2026-07-22)

**Query grammar** (SDMX 2.1 REST):
```
{base}/data/{agencyID},{dataflowID},{version}/{KEY}?startPeriod=…&endPeriod=…
```
where `KEY` is the dot-separated dimension filter (`+` = OR within a dimension, empty = all). Format is chosen by the `Accept` header, e.g. `application/vnd.sdmx.data+csv;labels=name` for labelled CSV, or `…+json` for SDMX-JSON. The dataflow's dimension order/codes come from its data-structure definition (DSD), fetchable at `{base}/datastructure/{agency}/{DSD_id}/?references=children`.

**Concrete, verified example — population aged 25-29 by sex, US+JP+DE, 2021** (returns real numbers):
```
https://sdmx.oecd.org/public/rest/data/OECD.ELS.SAE,DSD_POPULATION@DF_POP_HIST,/USA+JPN+DEU.POP.PS.F+M.Y25T29.?startPeriod=2021&endPeriod=2021
```
→ e.g. `USA,Female,Y25T29,2021 = 10,861,292`; `JPN,Female = 3,103,337`; `DEU,Male = 2,549,240`. The 6 dimensions are `REF_AREA.MEASURE.UNIT_MEASURE.SEX.AGE.TIME_HORIZ`.

**Rate limits (verified against OECD API-best-practices page):** **60 downloads/hour** per client, exceeding it → temporary block; the cap **also applies to CSV downloads from the data-explorer.oecd.org UI**. `lastNObservations`/`firstNObservations` **are blocked** (they let users sort billion-row datasets and strain the server). For >10M-record pulls, slice the query. Recommendation: **cache locally** (we pull each country's marginals once and store them — trivially within budget).

---

## 2. Per-dimension availability (US / JP / DE)

### 2a. Population by age × sex — ✅ 5-year bands, direct cross-tab
Dataflow `OECD.ELS.SAE:DSD_POPULATION@DF_POP_HIST` ("Historical population data"), landing `https://data-explorer.oecd.org/vis?df[id]=DSD_POPULATION@DF_POP_HIST` (checked 2026-07-22). `CL_AGE` exposes full **5-year bands** (`Y0T4, Y5T9, …, Y80T84, Y_GE85`) plus single years; `CL_SEX` = `F/M/_T`. Annual from 1950s. **Coverage includes non-members** (dataset explicitly lists EU27, G20, Argentina, Brazil, **China, India**, Indonesia, Russia, Saudi Arabia, Singapore, South Africa, World). This is the cleanest dimension: **age × sex is a genuine joint** for every country we care about.

### 2b. Educational attainment by age × sex — ✅ native ISCED-2011, direct three-way cross-tab
Dataflow `OECD.EDU.IMEP:DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA` ("Adults' educational attainment distribution, by age group and gender"), from Education at a Glance. Landing `https://data-explorer.oecd.org/vis?df[id]=DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA` (checked 2026-07-22).

- **Dimensions** (verified from DSD): `REF_AREA . SEX . AGE . ATTAINMENT_LEV . EDUCATION_FIELD . MEASURE . INCOME . …` — SEX, AGE and ATTAINMENT_LEV are all filterable **simultaneously**, so this is a **real age × sex × education three-way cross-tab**, not three separate marginals.
- **Measure** is `PT_POP_SEX_AGE` = "percentage of population in the same sex and age" → i.e. the **education distribution conditional on each (sex, age) cell**. That is exactly the conditional we need for raking.
- **Verified query** (adults 25-64, both sexes, three ISCED bands, US+JP+DE, 2023):
  ```
  https://sdmx.oecd.org/public/rest/data/OECD.EDU.IMEP,DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA,/USA+JPN+DEU.F+M.Y25T64.ISCED11A_0T2+ISCED11A_3_4+ISCED11A_5T8.............?startPeriod=2023&endPeriod=2023
  ```
  → e.g. Japan 2023, females 25-64, tertiary (`ISCED11A_5T8`) = **57.7%**. (17 dimensions in this DSD; trailing dots default to `_T`/all.)
- **Age granularity caveat:** the education `CL_AGE` offers **broad groups** (`Y25T34, Y25T44, Y25T64, Y35T44, Y45T54, Y55T64`, plus a few 5-year like `Y25T29, Y30T34`) — **NOT** the full 5-year ladder that population uses. So education can be raked against **coarse** age bands only; below ~10-year resolution, age × education must be treated as independent within the group.

### 2c. Income distribution — ⚠️ OECD IDD, **age-only breakdown**, the weak point
Dataflow `OECD.WISE.INE:DSD_WISE_IDD@DF_IDD` (the **OECD Income Distribution Database, IDD**). Dataset page: `https://www.oecd.org/en/data/datasets/income-and-wealth-distribution-database.html`; explorer `https://data-explorer.oecd.org/vis?df[id]=DSD_WISE_IDD@DF_IDD` (checked 2026-07-22).

- **Dimensions** (verified from DSD): `REF_AREA . FREQ . MEASURE . STATISTICAL_OPERATION . UNIT_MEASURE . AGE . METHODOLOGY . DEFINITION . POVERTY_LINE`. **There is no SEX dimension and no EDUCATION dimension.** This is the single most important finding of this note.
- **AGE** takes only coarse population groups: `_T` (total), `Y18T65` (working-age), `Y_GT65` (retirement), plus young/mid/old. So income is resolvable **by broad age group**, nothing finer.
- **Measures** include quantile-based inequality stats: `INC_DISP_GINI` (Gini), `D9_1_INC_DISP` (P90/P10 decile ratio), `D5_1_INC_DISP`, `QR_INC_DISP` (quintile ratio, ~S80/S20), `PAL_INC_DISP` (Palma), and `INC_DISP` (mean/median disposable income). **Verified query** returning real Ginis:
  ```
  https://sdmx.oecd.org/public/rest/data/OECD.WISE.INE,DSD_WISE_IDD@DF_IDD,/USA+JPN+DEU.A.INC_DISP_GINI......?startPeriod=2021&endPeriod=2022
  ```
  → DEU 2022 Gini (disposable) = 0.309; USA 2022 = 0.408; and by age group DEU >65 = 0.301, 18-65 = 0.312.
- **What this means for us:** IDD gives an **overall income distribution shape** (deciles / inequality ratios) per country, optionally split by working-age vs retirement. It does **not** give income conditional on sex, nor on education. So the income dimension arrives essentially as a **country-level (× coarse-age) marginal**, and to turn deciles into an income-quintile attribute per persona we anchor on the country distribution, not on demographics.

### 2d. Gender × income — pay-gap ratio only
The **gender wage gap** is published (Earnings Distribution Database / OECD Employment Database; indicator page `https://www.oecd.org/en/data/indicators/gender-wage-gap.html`, explorer view `https://data-explorer.oecd.org/s/499`, checked 2026-07-22) as the difference between male and female **median earnings** relative to male median. That is a **single summary statistic** describing the sex↔income relationship, **not** a joint income×sex distribution and not decile-by-sex. It is enough to *tilt* an imputed gender×income relationship (shift female personas' income position by the pay-gap ratio), but it is not an observed joint.

---

## 3. Joint granularity — the key question (OBSERVED vs IMPUTED)

This maps directly onto our per-dimension-pair fidelity descriptor. "OBSERVED" = OECD publishes it as an actual cross-tab we can rake against; "IMPUTED-INDEPENDENT" = not in OECD, must be assumed independent (or borrowed from the pay-gap / a fallback source).

| Dimension pair | OECD status | Source / note |
|---|---|---|
| **age × gender** | **OBSERVED** ✅ | `DF_POP_HIST`, 5-year bands × F/M — direct cross-tab |
| **age × education** | **OBSERVED (coarse age)** ✅ | `DF_LSO_NEAC_DISTR_EA`, ISCED conditional on age group — but only broad age groups (25-34, 45-54, 25-64…), not 5-year |
| **gender × education** | **OBSERVED** ✅ | same dataflow — ISCED conditional on sex; and full **age × sex × education** three-way is available together |
| **education × income** | **IMPUTED-INDEPENDENT** ❌ | IDD has no education dim; not published anywhere in OECD as a cross-tab. **Genuinely missing.** |
| **gender × income** | **PARTIAL / IMPUTED** ⚠️ | no joint distribution; only the **median pay-gap ratio** (a scalar). Impute independence then apply the pay-gap tilt. |
| **age × income** | **PARTIAL (coarse)** ⚠️ | IDD splits income by working-age (18-65) vs retirement (>65) only — a 2-3 bucket relationship, not a distribution per 5-year band |

**So OECD directly observes the entire DEMOGRAPHIC block (age × gender × education).** Everything touching **income** is either missing (education×income), scalar-only (gender×income pay gap), or coarse (age×income = 2 buckets). Income enters our IPF essentially as a **country marginal** and its correlations with the demographic axes are **imputed independent** (optionally nudged by the pay gap and the working/retirement split).

---

## 4. Education harmonization — ✅ native ISCED-2011, no per-country crosswalk

The attainment dimension `ATTAINMENT_LEV` (`CL_ATTAINMENT_LEV`) is **already coded in ISCED 2011** (`ISCED11A_*`). Verified codes include the exact three-way collapse we want:
- `ISCED11A_0T2` = **below upper secondary** (our "below-secondary")
- `ISCED11A_3_4` = **upper secondary + post-secondary non-tertiary** (our "secondary")
- `ISCED11A_5T8` = **tertiary** (our "tertiary")

plus finer levels (`ISCED11A_3`, `_4`, `_5`, `_6`, `_7`, `_8`, `_6T8`, `_7_8`, …). **This eliminates the per-country education crosswalk** that `demographic-sources.md` had to build manually for Japan's "type of last school completed" and Germany's dual schooling×vocational scheme. OECD ships the crosswalk already applied. High confidence — read directly off the DSD codelist and confirmed the labels in returned data ("Below upper secondary education", "Tertiary education").

---

## 5. Coverage ceiling — members (+ some partners) only

- **US / JP / DE: all present** in all three core dataflows (verified with live queries returning data for each).
- **Ceiling:** OECD ≈ its **38 member countries** plus selected **key partners / accession countries**. `DF_POP_HIST` (population) reaches further — it explicitly includes China, India, Indonesia, Brazil, Russia, South Africa, etc. — but the **education (EAG)** and **income (IDD)** databases are essentially **member-focused**; a non-member like **China or India will have age×sex population but little/no OECD education-attainment or IDD income coverage.**
- **What a non-member requires:** a fallback source per dimension — **World Bank** (education attainment via WDI/`SE.*` indicators; income deciles via the **Poverty and Inequality Platform, PIP**) and/or **UN Data / UNESCO UIS / ILOSTAT**. See §6.

---

## 6. Fallback assessment — filling the income (and non-member) gap via one API

The income joint is OECD's weak point, so name the fallback explicitly:

- **World Bank Poverty and Inequality Platform (PIP)** — public API, `https://pip.worldbank.org/api` (docs) / `https://api.worldbank.org/pip/` — covers **160+ countries** including US/JP/DE **and** non-members (China, India, Indonesia). Provides **decile thresholds / decile income shares by country and year** from harmonized household surveys. This is the natural single-API source for the **income deciles** dimension (turns directly into income quintiles) and for **non-member income**. It still does **not** give income×education or income×sex jointly — that gap is intrinsic to published aggregate data, not specific to OECD.
- **World Bank WDI** (`https://api.worldbank.org/v2/…`, keyless) — educational-attainment marginals (`SE.*`) and population for non-members, one REST API.
- **OECD IDD specifics we CAN use:** the working-age (18-65) vs retirement (>65) Gini/decile split gives a real (if coarse) **age × income** anchor, and the **gender pay-gap ratio** gives a defensible tilt for **gender × income**. Neither makes education×income observable.

**Recommendation:** keep **OECD as the primary harmonized source** for age×gender×education (+ the income *marginal* via IDD), and treat **World Bank PIP** as the income-distribution fallback (better global coverage of deciles, one keyless API) and the **non-member** backstop. Income's correlations with demographics remain imputed regardless of source — that is a property of the world's published data, and it must be declared in our fidelity descriptor.

---

## 7. Machine-readable summary

```yaml
# OECD-as-single-source assessment for age x gender x education x income joint.
api:
  name: OECD Data Explorer / SDMX REST API
  base_url: https://sdmx.oecd.org/public/rest
  keyless: true            # verified: live queries return data with no token
  formats: [sdmx-csv, sdmx-json, sdmx-xml]   # via Accept header
  query_grammar: "{base}/data/{agency},{dataflow},{version}/{DOT.SEPARATED.KEY}?startPeriod=&endPeriod="
  rate_limit: "60 downloads/hour per client (also caps UI CSV downloads)"
  blocked_params: [lastNObservations, firstNObservations]

dimensions:
  population_age_sex:
    dataflow: OECD.ELS.SAE:DSD_POPULATION@DF_POP_HIST
    key_order: [REF_AREA, MEASURE, UNIT_MEASURE, SEX, AGE, TIME_HORIZ]
    age_granularity: 5_year_bands        # Y0T4 ... Y_GE85
    sex: [F, M, _T]
    us_jp_de: present
    non_member_coverage: broad           # incl CHN, IND, IDN, BRA, RUS, ZAF, World
    cross_tab: age_x_sex_direct

  education_attainment:
    dataflow: OECD.EDU.IMEP:DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA
    filters_together: [SEX, AGE, ATTAINMENT_LEV]   # true 3-way cross-tab
    measure: PT_POP_SEX_AGE               # % within each (sex,age) cell
    education_scheme: ISCED_2011_native   # ISCED11A_0T2 / 3_4 / 5T8 = our 3-way collapse
    age_granularity: broad_groups         # 25-34, 25-64, 45-54, ...; NOT full 5-year
    us_jp_de: present
    non_member_coverage: members_mostly

  income:
    dataflow: OECD.WISE.INE:DSD_WISE_IDD@DF_IDD   # OECD IDD
    dimensions: [REF_AREA, FREQ, MEASURE, STATISTICAL_OPERATION, UNIT_MEASURE, AGE, METHODOLOGY, DEFINITION, POVERTY_LINE]
    has_sex_dim: false                    # <-- verified absent
    has_education_dim: false              # <-- verified absent
    age_breakdown: [_T, Y18T65, Y_GT65]   # working-age / retirement / total only
    measures: [INC_DISP_GINI, D9_1_INC_DISP, D5_1_INC_DISP, QR_INC_DISP, PAL_INC_DISP, INC_DISP]
    us_jp_de: present
    non_member_coverage: members_mostly

joint_pairs:                              # OBSERVED vs IMPUTED for the fidelity descriptor
  age_x_gender:      OBSERVED             # DF_POP_HIST, 5-year x F/M
  age_x_education:   OBSERVED_COARSE_AGE  # EAG, broad age groups only
  gender_x_education: OBSERVED            # EAG (also full age x sex x edu together)
  education_x_income: IMPUTED_INDEPENDENT # not published in OECD at all
  gender_x_income:   PARTIAL_PAYGAP       # only median pay-gap ratio (scalar), not a joint
  age_x_income:      PARTIAL_COARSE       # working-age vs retirement buckets only

fallbacks:
  income_distribution: World Bank PIP API (pip.worldbank.org/api)  # deciles, 160+ countries, keyless
  non_member_education_population: World Bank WDI (api.worldbank.org/v2)  # keyless
  gender_income_tilt: OECD gender wage gap indicator                # scalar tilt only

verdict:
  demographic_block_age_gender_education: OECD_sufficient_single_source
  income_joint_with_demographics: WEAK   # income is effectively a country marginal
  education_isced_native: true
  single_source_overall: partial         # yes for demographics; income correlations imputed
```

---

## 8. Confidence flags & honest gaps

- **Keyless API + query grammar:** HIGH — verified by issuing live queries that returned real observations for US/JP/DE with no auth.
- **IDD has no sex/education dimension:** HIGH — read directly off the DSD dimension list AND confirmed the returned data carries only REF_AREA/AGE/MEASURE/etc. This is the load-bearing negative finding; it is verified, not inferred.
- **Education is native ISCED-2011:** HIGH — codelist `CL_ATTAINMENT_LEV` uses `ISCED11A_*` ids and returned labels ("Below upper secondary", "Tertiary") confirm.
- **Education age granularity is coarse:** MEDIUM-HIGH — `CL_AGE` for the EAG dataflow exposes mainly broad groups; a few 5-year codes exist (`Y25T29`, `Y30T34`) but not a full ladder, and their population coverage per country was not exhaustively probed. Treat age×education as reliable at ~10-year resolution.
- **Rate limit = 60/hour:** MEDIUM — from the OECD API-best-practices page via search summary (the page 403s automated fetch); the 20→60 raise is documented. Our usage (cache each country once) is far under any version of the cap.
- **Non-member education/income coverage:** MEDIUM — asserted from dataset descriptions (EAG/IDD are member-centric) rather than an exhaustive per-country probe; population's wide coverage IS verified. Confirm specific non-members against the API before relying on them.
- **Exact IDD decile-share vs decile-ratio semantics:** MEDIUM — confirmed decile *ratios* (`D9_1` etc.) and Gini are present; whether per-decile mean income (10 threshold points) is exposed for all of US/JP/DE was not fully enumerated. Verify when wiring the income-quintile mapping (or use World Bank PIP, which publishes decile shares directly).

---

## 9. Verdict — can OECD be the single source?

**For age × gender × education: YES.** One keyless API, three dataflows, education already on ISCED-2011, and the three demographic pairs (age×gender, age×education, gender×education) are all **directly observed** cross-tabs — a clean upgrade over the per-country ACS/Destatis/e-Stat downloads. This alone justifies the pivot for the demographic block.

**For the full age × gender × education × income joint: NO, not by itself.** The OECD IDD breaks income down **by age group only** — it has **no sex dimension and no education dimension** — so:
- `education × income` is **not observable anywhere in OECD** → **IMPUTED independent**.
- `gender × income` exists only as the **median pay-gap ratio** (a scalar) → impute independence, then tilt by the pay gap.
- `age × income` is only working-age vs retirement (2-3 buckets) → coarse.

**How weak is the income joint, and the fallback:** income effectively enters as a **country-level marginal distribution** (deciles / Gini), and all its correlations with the demographic axes are imputed. This is not an OECD deficiency per se — published aggregate statistics essentially never cross a full income distribution with education. The cleanest fallback for the income marginal (and for non-member countries) is the **World Bank Poverty and Inequality Platform (PIP) API** (keyless, 160+ countries, decile shares) — a second single API, not a per-country scramble. **Net: adopt OECD as the harmonized backbone for age×gender×education + the income marginal; declare income's correlations as imputed-independent in the fidelity descriptor; keep World Bank PIP as the income/non-member fallback.**

---

## Sources (primary, checked 2026-07-22)

**OECD API**
- OECD SDMX REST API (live, queried directly): `https://sdmx.oecd.org/public/rest` — data, datastructure, dataflow endpoints
- OECD Data Explorer API page: `https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html` · FAQ `…/2024/09/OECD-DE-FAQ.html` · **API best practices** (rate limits, blocked params) `…/2024/11/Api-best-practices-and-recommendations.html`
- SDMX-JSON documentation: `https://data.oecd.org/api/sdmx-json-documentation/`

**Datasets / dataflows (verified via API + landing pages)**
- Population by age × sex — `OECD.ELS.SAE:DSD_POPULATION@DF_POP_HIST`: `https://data-explorer.oecd.org/vis?df%5Bid%5D=DSD_POPULATION@DF_POP_HIST`
- Educational attainment by age × sex (ISCED) — `OECD.EDU.IMEP:DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA`: `https://data-explorer.oecd.org/vis?df%5Bid%5D=DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA`
- Income Distribution Database (IDD) — `OECD.WISE.INE:DSD_WISE_IDD@DF_IDD`: dataset `https://www.oecd.org/en/data/datasets/income-and-wealth-distribution-database.html` · IDD terms of reference `https://www.oecd.org/content/dam/oecd/en/data/datasets/income-and-wealth-distribution-databases/idd-tor-2012-onwards.pdf`
- Gender wage gap (Earnings Distribution Database / Employment DB): `https://www.oecd.org/en/data/indicators/gender-wage-gap.html` · `https://data-explorer.oecd.org/s/499`

**Harmonization**
- ISCED 2011 (UNESCO / OECD operational manual): `https://www.oecd.org/en/publications/isced-2011-operational-manual_9789264228368-en.html`

**Fallbacks**
- World Bank Poverty and Inequality Platform (PIP) API: `https://pip.worldbank.org/api` · `https://pip.worldbank.org/use-pip`
- World Bank WDI API (keyless): `https://api.worldbank.org/v2/`
