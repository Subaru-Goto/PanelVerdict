# Demographic Data Sources — joint (age × gender × income × education × region) for the persona pool (research for ticket 006b)

*Date: 2026-07-21 · Method: primary-source retrieval against official national statistics agencies (US Census Bureau, Destatis / German FDZ, Japan Statistics Bureau / e-Stat) and IPUMS official documentation. Every availability/licensing claim below was checked against the actual source page on the date noted, NOT asserted from memory. Feeds ticket 006b "persona pool: sample joint demographics per country." Scope: US, Germany, Japan. Demographics only — Big Five norms are sourced separately in `persona-seed-data.md`.*

> **Status: strategy + access map — read the confidence flags.** The headline result: the three countries fall into three *different* buckets. **US = sample directly** from public individual-level microdata (ACS PUMS). **Germany = partial** — census demographics are gettable (harmonized via IPUMS-International, free-but-registered), but **income joint with demographics is only in the Mikrozensus behind a German research-data-centre wall**, so income must be reconstructed from public aggregate cross-tabs. **Japan = reconstruct entirely** — no public individual-level microdata, and **the census does not collect income at all**, so the joint must be built from separate aggregate tables via IPF/raking. IPUMS-International covers **Germany but NOT Japan**. Details and honest gaps below.

---

## TL;DR — what 006b gets, per country

| Country | Public individual microdata w/ age+gender+income+education+region jointly? | Strategy | Application to a research data centre needed for the *ideal* source? |
|---|---|---|---|
| **United States** | **Yes** — ACS PUMS, all five attributes, free public download | **Sample directly** from PUMS | No |
| **Germany** | **No.** Census demographics (age×gender×education×Land) are public/harmonizable, but **income is only in the Mikrozensus SUF** (German-institution application + fee) | **Hybrid: sample demographics** (IPUMS-I 2011 census or Destatis cross-tabs) **+ IPF-fold income** from public Mikrozensus income cross-tabs | Yes for the *ideal* (Mikrozensus SUF with continuous joint income) — **infeasible on a ~2-week timeline** without a German research affiliation; the public route avoids it |
| **Japan** | **No.** No public PUMS; anonymized microdata is application-gated + academic-only; **the Population Census collects no income** | **Reconstruct via IPF** from public e-Stat census cross-tabs (age×gender×education×prefecture) **+ bridge income** from a *separate* income survey (FIES / National Survey of Family Income, Consumption & Wealth) | Yes for the *ideal* (on-site / anonymized microdata via miripo–NSTAC) — **infeasible on a ~2-week timeline**; the public aggregate route avoids it |

**IPUMS-International (single harmonized cross-country source?):** covers **Germany (census samples 1970, 1971, 1981, 1987, 2011)** but **does NOT cover Japan** — Japan has not agreed to disseminate census microdata through IPUMS. And even the German IPUMS samples **carry no income variable** (verified). So IPUMS-I is *not* a one-stop shop for all three; it's a clean harmonized route for US and German *demographics only*.

**Harmonization recommendation:** education → **ISCED 2011** levels (IPUMS `EDATTAIN` is already ISCED-derived, giving a ready crosswalk); income → **within-country income quantiles** (deciles/quintiles), NOT PPP-converted absolute values — because German and Japanese income arrive as *brackets from different surveys/currencies*, quantiles keep each country internally congruent and sidestep PPP/currency comparability arguments the sampler doesn't need.

---

## 1. United States — ACS PUMS (sample directly) ✅

**Source:** U.S. Census Bureau, American Community Survey **Public Use Microdata Sample (PUMS)**.
- Landing: `https://www.census.gov/programs-surveys/acs/microdata.html` (checked 2026-07-21)
- Access: `https://www.census.gov/programs-surveys/acs/microdata/access.html`
- Documentation / variable list: `https://www.census.gov/programs-surveys/acs/microdata/documentation.html`

**Is it public individual-level microdata with all five attributes jointly? — YES.** PUMS files are untabulated records for individual persons/housing units. All five target attributes are present on the same person record:

| Attribute | PUMS variable | Notes |
|---|---|---|
| Age | `AGEP` | single years |
| Gender | `SEX` | male/female (ACS binary) |
| Income | `PINCP` (total personal income), also `WAGP` (wages), `HINCP` (household); requires `ADJINC` inflation adjustment | **continuous $** (top-coded) |
| Education | `SCHL` (educational attainment) | ~24 US attainment categories; universe age 3+ |
| Region | `PUMA` (Public Use Microdata Area) nested in state; also region/division | PUMA is the finest geography (~100k+ population units); state identified |

**Access & licensing:** freely downloadable, **no registration required**, via data.census.gov microdata tool, the Census FTP site (CSV + SAS, person and housing files), and the Census API. Available as 1-year (~1% of population) and 5-year (~5%) files. **Licensing:** U.S. federal government statistical products; Census Bureau PUMS is distributed for free public use. *Confidence flag:* I confirmed free/unrestricted public availability from the Census pages but did **not** locate a single explicit license-text URL — treat as "U.S.-gov public-domain-style, no attribution/registration barrier," which is the standard understanding, and cite the specific terms page if a formal license line is needed in code.

**Alternative harmonized route:** **IPUMS USA** (`https://usa.ipums.org`) wraps the same ACS/decennial data with harmonized variable coding. Access: free, **register** (institutional/affiliation info), **approval is instantaneous**, build an extract, download in ~<1 hour. Use IPUMS USA if you want US variables already coded to match a cross-country harmonized scheme (e.g. IPUMS `EDATTAIN`); use raw Census PUMS if you want zero registration.

**Verdict for 006b:** trivial — draw persons directly from PUMS (weighted by `PWGTP`). The joint distribution *is* the file.

---

## 2. Germany — census demographics public, income behind the FDZ wall ⚠️

Germany has **several** microdata products with **very different access tiers**. The distinction is the whole story here.

### 2a. Mikrozensus (the ideal income-carrying source) — SUF is application-gated
The **Mikrozensus** (1% household sample, ~370k households) carries age, sex, **net income in brackets** (Nettoeinkommen), education (school + vocational qualifications), and **Bundesland** (Land) jointly — exactly the joint we want. But the individual-level file is a **Scientific Use File (SUF)** distributed by the **Forschungsdatenzentrum der Statistischen Ämter (Research Data Centre)**:
- SUF page: `https://www.forschungsdatenzentrum.de/en/scientific-use-files` (checked 2026-07-21)
- Microcensus: `https://www.forschungsdatenzentrum.de/en/household/microcensus`
- **Access barrier:** the requesting **institution must be located in Germany**, data used only on the premises of the requesting German scientific institution, all users bound to statistical confidentiality under §16(7) BStatG, and an **off-site SUF costs €225**. This is a formal research-data-centre application → **infeasible on a ~2-week timeline without a German research affiliation.**

### 2b. Public / free German microdata — exists, but stripped or dated
- **Public Use Files (PUF):** `https://www.forschungsdatenzentrum.de/en/public-use-files` — **absolutely anonymised**, free after registration, usable anywhere. **Trade-off:** strong anonymisation means "only selected variables … variables of high subject-related detail aggregated," so the fine *joint* income×education×region granularity we need is degraded.
- **CAMPUS-Files:** free public-use files for *teaching* (e.g. Mikrozensus **1998**, 195 variables vs the SUF's 332). Free, but **dated** and coarsened for pedagogy — a fallback for prototyping the sampler mechanics, not a 2026 population source.

### 2c. GSOEP (SOEP) — rich, but contract-gated
The Socio-Economic Panel (DIW Berlin) has individual-level income, education, region — but **cannot be downloaded openly**. A **data distribution contract with DIW Berlin** is required, **individuals without an institutional affiliation are not permitted to use it**, and delivery is by encrypted download / DVD (€38). Contract barrier → same timeline problem as the Mikrozensus SUF.
- `https://www.diw.de/en/diw_01.c.601584.en/data_access.html` (checked 2026-07-21)

### 2d. IPUMS-International Germany — free-but-registered, and **no income**
IPUMS-I has harmonized German **census** samples: **1970 (West), 1971 (East), 1981 (East), 1987 (West), 2011**. Access is free but **restricted**: submit an authorization form (name, institutional affiliation, project purpose), individually reviewed by staff (~2 working days), registration expires yearly.
- Samples: `https://international.ipums.org/international-action/samples`
- **Verified gap:** the IPUMS-I income variable group shows **no income data for any German sample** (`.` across DE 1970/71/81/87). The German **Zensus 2011 is register-based and does not collect personal income**, so IPUMS-I Germany gives age × gender × education × geography but **not income**.

### 2e. Public aggregate cross-tabs — Destatis / GENESIS
Destatis publishes Mikrozensus and Zensus **aggregate tables** via GENESIS-Online (`https://www-genesis.destatis.de`) and the Zensus database (`https://www.zensus2022.de`). These give published cross-tabs (e.g. age×sex×Land; educational attainment by age/sex; income brackets by household type) but as **lower-dimensional marginals/cross-tabs**, not the full 5-way joint.

### Native category schemes (Germany)
- **Income:** Mikrozensus uses **monthly net income brackets** (Nettoeinkommensklassen, in €); GSOEP has continuous income. Public tables are bracketed.
- **Education:** German dual scheme — **general schooling** (kein Abschluss / Hauptschule / Realschule (Mittlere Reife) / Fachhochschulreife / Abitur (allgemeine Hochschulreife)) **× vocational** (kein / Lehre-Ausbildung / Fachschule / Fachhochschule (FH) / Universität). Maps onto ISCED 2011 (see §5).
- **Region:** **16 Bundesländer (Länder)**. (SUF suppresses finer geography for anonymisation; Land is the reliable public unit.)

**Verdict for 006b:** **Hybrid.** Sample **age × gender × education × Land** from IPUMS-I 2011 (free, registered) or Destatis cross-tabs, then **fold income in via IPF/raking** against public Mikrozensus income-bracket cross-tabs (income × age-band, income × Land). Reserve the Mikrozensus SUF as the "ideal but application-gated" upgrade — flag in code that it needs a German research affiliation and is out of scope for the current timeline.

---

## 3. Japan — no public microdata; census has no income → reconstruct ❌ microdata

### Update (2026-07-21) — individual-income source found (user-supplied); frame mismatch resolved

The household-vs-individual frame mismatch flagged below is **fixed by a better source**: the **就業構造基本調査 (Employment Status Survey, Statistics Bureau, 2022; ~540k households / ~1.08M persons aged 15+)**. Per its glossary (§20 所得) + survey-items list, it collects **individual annual income (所得, main job — self-employed = business profit, employees = gross pay) jointly with age × sex × education × prefecture × employment status**, *and* household income (世帯所得, §8). This is the **same-survey, same-frame** individual income source we wanted — no cross-survey household bridge.

- Income cross-tabs live in this survey's full e-Stat 統計表 (the published 結果の概要 booklet doesn't tabulate 所得 — pull the specific 所得 × age × sex (× education/prefecture) table on e-Stat when wiring IPF).
- **Corroborating / gap-fill:** 賃金構造基本統計調査 (Basic Survey on Wage Structure, 2025) publishes clean income × age × sex × **education** × prefecture cross-tabs *directly* — but **employees only** (excludes self-employed + non-workers). Use it for the employee income-by-education gradient; use the Employment Status Survey for full coverage.
- Education categories (小中 / 高校 / 専門学校 / 短大・高専 / 大学 / 大学院) map cleanly to **ISCED**.
- **Nuance:** individual work-income (所得) applies to workers (有業者); non-working personas (≈39% of 15+) should draw **household income (世帯所得)** instead — both are in the same survey.

**Revised strategy:** still IPF from public cross-tabs (no public microdata), but the income targets are now **individual and same-frame** → **Japan upgrades from 🔴 to 🟡** (on par with Germany's income-IPF). The census-vs-income frame mismatch is no longer the pipeline's weak link. (The §3c/§3d notes below describe the *superseded* household-bridge fallback — kept for context.)

### 3a. No public PUMS-equivalent; microdata is application-gated
Japan's official-statistics microdata regime (post-2007 Statistics Act) offers three secondary-use routes — **on-site use**, **custom-made tabulation**, and **anonymized data (匿名データ)** — all administered through the **Micro Data Usage Portal "miripo"** and the National Statistics Center (NSTAC), and all **require an application and a usage fee**, with use restricted to **academic research / higher education**.
- Statistics Bureau overview: `https://www.stat.go.jp/english/` (checked 2026-07-21)
- Secondary-use / extended-use (MIC): `https://www.soumu.go.jp/english/dgpp_ss/seido/2jiriyou.htm`
- NSTAC: `https://www.nstac.go.jp/`
- **There is no freely downloadable individual-level microdata file.** *Confidence flag:* eligibility of a non-academic / non-Japanese applicant for anonymized data is **unclear from the English pages** — I could not confirm a commercial synthetic-persona project would qualify. Treat anonymized-data microdata as **not available on this timeline.**

### 3b. IPUMS-International — **does NOT cover Japan**
Verified: Japan does not appear in the IPUMS-I sample list. Japan has **not agreed** to disseminate census microdata through IPUMS-International. So the harmonized cross-country route that works for Germany is **unavailable for Japan.**

### 3c. The census collects **no income** — critical structural gap
Japan's **Population Census** (Statistics Bureau, quinquennial; 2020 is latest) does **not collect income/earnings**. Income is collected by *separate* surveys:
- **Family Income and Expenditure Survey (FIES)** — `https://www.stat.go.jp/english/data/kakei/index.html`
- **National Survey of Family Income, Consumption and Wealth** (formerly National Survey of Family Income and Expenditure / 全国消費実態調査) — `https://www.stat.go.jp/english/data/zensho/index.html`

So **no single Japanese source** (public *or* application-gated census microdata) contains income jointly with the demographic attributes. Income must be **bridged from a different survey** onto the census demographic frame.

### 3d. Public aggregate cross-tabs — e-Stat (this is the workable route)
e-Stat (`https://www.e-stat.go.jp/en/`) publishes 2020 Population Census cross-tabs, free and downloadable, including the key one:
- **Age×gender×education×region:** Table "62-2 Population (aged 15+) by Sex, Age (five-year groups), Nationality and **type of last school completed** — Japan, Prefectures, major cities" (`e-Stat sid=0003450689`). This gives **age-band × sex × educational attainment × prefecture** publicly.
- Plus age×sex×prefecture (single-year and 5-year), socio-economic groups, employment/industry cross-tabs.
- **Income** cross-tabs (by household attributes, age of household head, region) come separately from FIES / the National Survey via e-Stat.

### Native category schemes (Japan)
- **Income:** currency **JPY**; from FIES / National Survey as **income brackets / quantile classes** by household (not individual, and not on the census).
- **Education:** "**type of last school completed**" — primary/lower-secondary (小学校・中学校), upper-secondary (高校/旧中), junior college / technical college (短大・高専), university (大学), graduate (大学院). Maps onto ISCED 2011 (see §5).
- **Region:** **47 prefectures (都道府県)**, groupable into the standard 8 regions (Hokkaido, Tohoku, Kanto, Chubu, Kinki, Chugoku, Shikoku, Kyushu-Okinawa); municipalities and major cities also published.

**Verdict for 006b (revised — see the 2026-07-21 update at the top of this section):** **IPF reconstruction from same-frame individual cross-tabs.** Build the demographic joint from the e-Stat census cross-tab (age×gender×education×prefecture), then IPF an **individual income** dimension on from the **就業構造基本調査 (Employment Status Survey)** — individual 所得 for workers + 世帯所得 for non-workers, same survey frame — with 賃金構造基本統計調査 as the employee income-by-education corroborator. The earlier household-survey (FIES) bridge is the *superseded fallback*.

---

## 4. Cross-cutting: IPUMS-International as a single source

**Coverage (verified 2026-07-21):**
- **Germany: YES** — census samples 1970 (West), 1971 (East), 1981 (East), 1987 (West), 2011. **But no income variable in any German sample.**
- **Japan: NO** — not a participating country; no samples exist.
- **US: YES** via IPUMS USA (separate project; ACS 2000→present, decennial 1790–2010).

**Access model:** IPUMS USA = free, register, **instant** approval. IPUMS-International = free but **restricted** — application with institutional affiliation + project purpose, human-reviewed (~2 working days), 1-year renewable registration. Classroom accounts exist. So IPUMS is a **low-friction (not zero-friction)** route for US + German demographics, and **irrelevant for Japan.**

**Conclusion:** IPUMS-I is **not** the hoped-for one-source-for-all-three. It cleanly harmonizes US and German *demographics*, contributes **nothing for Japan**, and **no income for Germany**.

---

## 5. Harmonization standards

### Education → ISCED 2011 (recommended)
**ISCED 2011** (UNESCO Institute for Statistics) is the international standard for mapping national education systems onto common levels (0 early-childhood … 8 doctoral). Use it as the canonical target scheme; map each country's native categories onto ISCED main levels:

| ISCED 2011 | US `SCHL` (grouped) | Germany (schooling × vocational) | Japan (last school completed) |
|---|---|---|---|
| 0–1 primary | no schooling … grade 4 | kein Abschluss / Grundschule | 小学校 (primary) |
| 2 lower-secondary | grades 5–8 | Hauptschule / Mittlere Reife (lower) | 中学校 (lower-secondary) |
| 3 upper-secondary | HS diploma / GED | Realschule + Lehre / Abitur | 高等学校 (upper-secondary) |
| 4 post-secondary non-tertiary | some college, no degree | Fachschule / Berufsfachschule | (part of 専修学校) |
| 5–6 short-cycle / bachelor | associate / bachelor's | Fachhochschule (FH) / Bachelor | 短大・高専 / 大学 (bachelor) |
| 7–8 master/doctoral | master's / professional / doctorate | Universität / Master / Promotion | 大学院 (graduate) |

**Leverage:** IPUMS `EDATTAIN` (International) and IPUMS USA educational recodes are **already ISCED-derived** for the 2011-era samples — so if you pull demographics from IPUMS, education arrives pre-harmonized. For the Japanese e-Stat categories (no IPUMS), do the crosswalk manually per the table above. *Confidence flag:* the fine boundaries (esp. ISCED 4 vs 5, and where German vocational Ausbildung sits) are genuinely fuzzy across systems — collapse to **~5 coarse levels** (≤lower-sec / upper-sec / post-sec non-tertiary / bachelor-ish / master+) for a robust cross-country persona attribute rather than chasing all 9.

### Income → within-country quantiles (recommended over PPP)
Two options:
1. **PPP-converted absolute income** (e.g. via OECD/World Bank PPP factors) — lets you compare €/¥/$ on one axis, but adds a conversion assumption the persona sampler doesn't need, and fights the fact that German/Japanese public income data is **already bracketed** (and Japanese income is *household*, not individual).
2. **Within-country income quantiles** (quintiles/deciles) — **recommended.** Each persona's income is expressed as its position in *its own country's* distribution. This is congruent-by-construction with the per-country sampling design (issue 001), needs no currency/PPP argument, and maps cleanly onto the bracketed public data (assign each bracket to a quantile via its published population share). Keep the native currency band as a display attribute if a nominal figure is wanted.

---

## 6. Machine-readable summary (per-country sampler plan)

```yaml
# Data strategy per country for the 006b persona-pool sampler.
# attrs = age, gender, income, education, region

united_states:
  strategy: direct_microdata
  primary_source: ACS PUMS (US Census Bureau)
  access: public, no registration, free download (data.census.gov / FTP / API)
  joint_attrs_in_one_record: [age, gender, income, education, region]  # all five
  vars: {age: AGEP, gender: SEX, income: PINCP, education: SCHL, region: PUMA}
  weight: PWGTP
  harmonized_alt: IPUMS USA (free, instant registration)
  rdc_application_needed: false

germany:
  strategy: hybrid_demographics_direct_income_via_IPF
  demographics_source: IPUMS-International DE 2011 census  # OR Destatis/Zensus cross-tabs
  demographics_access: free but registered (application ~2 business days, institutional affiliation)
  demographics_joint: [age, gender, education, region]      # region = Bundesland (16 Laender)
  income_gap: "census/IPUMS-I German samples carry NO income (register-based census)"
  income_source_public: Destatis/GENESIS Mikrozensus income-bracket cross-tabs (aggregate marginals)
  income_source_ideal: Mikrozensus Scientific Use File (FDZ)  # continuous joint income
  income_method: IPF/raking income-brackets onto the demographic joint
  rdc_application_needed_for_ideal: true   # FDZ SUF: German institution + EUR225 + confidentiality; INFEASIBLE ~2wk

japan:
  strategy: full_IPF_reconstruction
  public_microdata: none    # anonymized microdata is application-gated + academic-only (miripo/NSTAC)
  ipums_international_coverage: false        # Japan does not participate
  demographics_source: e-Stat 2020 Population Census cross-tab (table 62-2)
  demographics_access: public, free download (e-Stat)
  demographics_joint: [age_band, gender, education, region]  # region = 47 prefectures; age in 5yr bands
  income_gap: "Population Census collects NO income (use a separate survey)"
  income_source: 就業構造基本調査 Employment Status Survey 2022  # INDIVIDUAL income (所得) + household income (世帯所得), same frame as demographics
  income_source_corroborating: 賃金構造基本統計調査 Basic Survey on Wage Structure  # income x age x sex x education x prefecture, published directly, EMPLOYEES ONLY
  income_source_superseded_fallback: FIES / National Survey  # household-level; only if ESS income cross-tabs prove unusable
  income_method: IPF/raking individual income (ESS) onto census demographic joint  # same-frame -> no household/individual mismatch
  income_note: "所得 = work income (workers); non-workers draw 世帯所得 (household income), also in ESS"
  microdata_ideal: on-site/anonymized via miripo-NSTAC       # application + fee; INFEASIBLE ~2wk

harmonization:
  education: ISCED_2011   # collapse to ~5 coarse levels; IPUMS EDATTAIN already ISCED-derived
  income: within_country_quantiles   # preferred over PPP-absolute; congruent-by-construction per issue 001

ipums_international:
  germany: true   # samples 1970,1971,1981,1987,2011 -- but NO income
  japan: false
  us_via_ipums_usa: true
  access: free_but_restricted   # application + institutional affiliation, ~2 business days
```

---

## 7. Confidence flags & honest gaps

- **US license text:** free/unrestricted public availability confirmed from Census pages; a single explicit license-URL was **not** located — treated as U.S.-gov public-domain-style. Low risk.
- **Japan anonymized-data eligibility:** English pages confirm application + fee + academic-only, but **do not confirm** whether a non-academic / non-Japanese / commercial project qualifies. I did **not** verify a path to Japanese microdata for this project — treated as unavailable. **This is the least-certain access claim in the doc.**
- **German Mikrozensus income bracket definitions:** confirmed bracketed net income exists in Mikrozensus/SUF; the **exact 2022/2023 bracket boundaries** were not extracted (they live in the SUF Datenhandbuch / GENESIS tables) — pull them when actually wiring the IPF targets.
- **Japan census↔income frame mismatch:** census demographics are **individual**, FIES/National-Survey income is **household** — the IPF bridge conflates the two frames. Flagged as the weakest link; acceptable for synthetic marketing personas, not for real income inference.
- **IPUMS-I German income = none:** **verified** against the IPUMS-I income variable group (`.` for all DE samples). High confidence.
- **IPUMS-I Japan = none:** **verified** against the IPUMS-I sample list. High confidence.
- **ISCED boundary fuzziness:** cross-system mapping of vocational/post-secondary levels (German Ausbildung, Japanese 専修学校/短大) is genuinely ambiguous — recommend collapsing to ~5 coarse levels rather than the full 9.

---

## Sources (primary, checked 2026-07-21)

**United States**
- U.S. Census Bureau — ACS PUMS: `https://www.census.gov/programs-surveys/acs/microdata.html` · access `…/microdata/access.html` · documentation `…/microdata/documentation.html`
- ACS 2024 1-Year PUMS User Guide: `https://www2.census.gov/programs-surveys/acs/tech_docs/pums/2024ACS_PUMS_User_Guide.pdf` (vars PINCP, SCHL, AGEP, SEX, PUMA)
- IPUMS USA (harmonized alt): `https://usa.ipums.org/usa/data.shtml` · FAQ `https://usa.ipums.org/usa-action/faq` (free, instant registration)

**Germany**
- FDZ Research Data Centre — Scientific Use Files: `https://www.forschungsdatenzentrum.de/en/scientific-use-files` · Microcensus `…/en/household/microcensus` · Public Use Files `…/en/public-use-files` · Access `…/en/access` (German-institution requirement, €225 off-site SUF, §16(7) BStatG)
- GESIS German Microdata Lab — Mikrozensus: `https://www.gesis.org/en/gml/microcensus`
- DIW Berlin — SOEP data access: `https://www.diw.de/en/diw_01.c.601584.en/data_access.html` (distribution contract; institutional affiliation required)
- IPUMS-International Germany samples: `https://international.ipums.org/international-action/samples` (1970/1971/1981/1987/2011) · income group `…/variables/group/inc` (no DE income)
- Destatis GENESIS-Online (aggregate cross-tabs): `https://www-genesis.destatis.de` · Zensus 2022: `https://www.zensus2022.de`

**Japan**
- Statistics Bureau of Japan: `https://www.stat.go.jp/english/`
- e-Stat Portal (census cross-tabs): `https://www.e-stat.go.jp/en/` · Census table 62-2 (age×sex×school completed×prefecture): `https://www.e-stat.go.jp/en/dbview?sid=0003450689`
- Extended (secondary) use of official statistics microdata (MIC): `https://www.soumu.go.jp/english/dgpp_ss/seido/2jiriyou.htm` · NSTAC: `https://www.nstac.go.jp/` (miripo; application + fee, academic use)
- Family Income and Expenditure Survey: `https://www.stat.go.jp/english/data/kakei/index.html` · National Survey of Family Income, Consumption & Wealth: `https://www.stat.go.jp/english/data/zensho/index.html`

**Harmonization**
- UNESCO ISCED 2011 (OECD operational manual): `https://www.oecd.org/en/publications/isced-2011-operational-manual_9789264228368-en.html`
- IPUMS-International EDATTAIN (ISCED-derived): `https://international.ipums.org/international-action/variables/edattain`
