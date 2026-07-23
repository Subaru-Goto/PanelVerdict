# Donnellan & Lucas (2008) — raw extracted numbers (Table 1 + Table 3)

Primary-source transcription for ticket 006c. Every number below was verified against the
actual PMC-hosted article HTML, not from memory. See "Confidence / gaps" at the bottom.

## Citation

Donnellan, M. B., & Lucas, R. E. (2008). Age differences in the Big Five across the life span:
Evidence from two national samples. *Psychology and Aging, 23*(3), 558–566.
doi:10.1037/a0012897. PMCID: PMC2562318; PMID: 18808245 (NIH author manuscript).

- **Table 1** — "Means and Standard Deviations for the Big Five T Scores by Age Categories"
- **Table 3** — "Effect Sizes for Gender and Education Differences by Age Categories"

Article page range 558–566. The PMC author-manuscript HTML does not print per-table page
numbers, so the exact printed page of each table is **UNAVAILABLE** (do not fabricate one).

## Where each block came from

- Table 1 grid: `https://pmc.ncbi.nlm.nih.gov/articles/PMC2562318/table/T1/` — read as rendered
  page text, then cross-checked cell-by-cell against a separate full-article fetch. Both agree.
- Table 3 (gender + education d's): `https://pmc.ncbi.nlm.nih.gov/articles/PMC2562318/table/T3/`
  — read as rendered page text. Matches the in-text "Gender and Education Effects" section.

---

## Table 1 — Big Five T-score means (SD in parentheses)

Column order as printed: **Extraversion, Agreeableness, Conscientiousness, Neuroticism, Openness.**
The leftmost data column is labelled **"Minimum Sample Size"** (per-trait N ranges slightly; this
is the minimum). Values are **T-scores** (M=50, SD=10) standardized *within each sample* to the
mean and SD of that sample's **age 30–34** subgroup (per the table note) — not to the whole-sample
or whole-population mean.

### BHPS (British Household Panel Study, UK)

| Age band | Min. N | Extraversion | Agreeableness | Conscientiousness | Neuroticism | Openness |
|----------|-------:|-------------:|--------------:|------------------:|------------:|---------:|
| 16–19 | 1,007 | 53.01 (9.86)  | 48.61 (10.61) | 42.76 (10.97) | 50.47 (10.86) | 50.45 (10.43) |
| 20–29 | 2,216 | 51.58 (9.93)  | 50.00 (10.11) | 47.88 (10.11) | 50.10 (10.36) | 51.08 (10.21) |
| 30–39 | 2,590 | 49.70 (10.33) | 50.43 (10.02) | 50.35 (10.21) | 49.92 (10.03) | 49.79 (10.16) |
| 40–49 | 2,625 | 48.54 (10.94) | 50.91 (10.03) | 50.82 (10.62) | 49.39 (10.34) | 48.64 (10.56) |
| 50–59 | 2,220 | 47.47 (11.03) | 51.32 (10.51) | 50.80 (10.99) | 48.99 (10.81) | 48.06 (11.45) |
| 60–69 | 1,697 | 46.98 (11.29) | 50.98 (11.37) | 49.24 (12.32) | 47.87 (11.17) | 46.28 (12.54) |
| 70–79 | 1,250 | 45.56 (12.35) | 51.43 (11.96) | 47.20 (13.21) | 46.25 (11.22) | 44.27 (13.58) |
| 80–85 | 434   | 45.41 (12.10) | 51.44 (11.92) | 46.77 (13.29) | 46.52 (11.74) | 42.47 (12.86) |

### GSOEP (German Socio-Economic Panel Study, Germany)

| Age band | Min. N | Extraversion | Agreeableness | Conscientiousness | Neuroticism | Openness |
|----------|-------:|-------------:|--------------:|------------------:|------------:|---------:|
| 16–19 | 1,344 | 51.17 (10.32) | 49.64 (10.26) | 41.49 (12.27) | 48.80 (9.96)  | 51.75 (10.44) |
| 20–29 | 2,835 | 50.94 (10.25) | 49.65 (9.97)  | 47.15 (10.92) | 49.99 (10.42) | 51.46 (9.89)  |
| 30–39 | 3,745 | 50.12 (9.96)  | 49.79 (10.17) | 50.22 (9.98)  | 50.04 (10.18) | 50.23 (9.90)  |
| 40–49 | 4,275 | 49.84 (9.99)  | 50.31 (10.16) | 51.22 (9.72)  | 50.36 (10.22) | 50.15 (10.18) |
| 50–59 | 3,271 | 49.08 (9.79)  | 50.21 (10.48) | 51.16 (10.23) | 51.10 (10.44) | 50.43 (10.68) |
| 60–69 | 3,293 | 48.27 (10.05) | 50.56 (10.45) | 50.23 (10.78) | 51.51 (10.32) | 49.43 (11.07) |
| 70–79 | 1,683 | 47.54 (10.28) | 52.46 (10.63) | 50.46 (10.69) | 51.38 (10.48) | 47.66 (11.62) |
| 80–84 | 403   | 47.57 (10.44) | 54.16 (10.23) | 49.84 (11.42) | 50.74 (11.41) | 45.56 (11.95) |

**Actual top age band differs by sample:** BHPS's is **80–85**, GSOEP's is **80–84** (each trimmed
to participants < 86 / < 85 respectively; the paper cut ages where n < 40). All lower bands are
identical across samples: 16–19, 20–29, 30–39, 40–49, 50–59, 60–69, 70–79.

Table note (verbatim): "BHPS = British Household Panel Study; GSEOP = German Socio-Economic Panel
Study; T scores were created by standardizing scores to the mean and SD for individuals ages 30 to
34 within each sample."

### Worked-example sanity check (passes)

Openness, 16–19: T_BHPS = **50.45**, T_GSOEP = **51.75**.
z = ((50.45 + 51.75)/2 − 50)/10 = (51.10 − 50)/10 = **+0.110**. Matches the expected z ≈ 0.110.

---

## Table 3 — Gender differences (Cohen's d)

**Sign convention (verbatim from the table note):** "Effect sizes for gender were calculated so
that positive scores indicated that **women scored higher than men**." (So d > 0 ⇒ female higher.)

Per-domain d, by age band, both samples. Column order: Extraversion, Agreeableness,
Conscientiousness, Neuroticism, Openness — each split BHPS / GSOEP.

| Age band | E BHPS | E GSOEP | A BHPS | A GSOEP | C BHPS | C GSOEP | N BHPS | N GSOEP | O BHPS | O GSOEP |
|----------|-------:|--------:|-------:|--------:|-------:|--------:|-------:|--------:|-------:|--------:|
| 16–19    | .38 | .24 | .29 | .31 | .13 | .34 | .57 | .47 | −.10 | .36 |
| 20–29    | .26 | .13 | .23 | .30 | .30 | .13 | .56 | .47 | −.18 | .17 |
| 30–39    | .27 | .18 | .39 | .26 | .16 | .12 | .45 | .45 | −.16 | .12 |
| 40–49    | .22 | .23 | .33 | .37 | .16 | .13 | .47 | .35 | −.21 | .19 |
| 50–59    | .16 | .17 | .38 | .39 | .08 | .06 | .64 | .30 | −.08 | .09 |
| 60–69    | .13 | .14 | .35 | .42 | .07 | .09 | .47 | .37 | −.14 | .08 |
| 70–79    | .08 | −.01| .19 | .38 | −.08| .03 | .51 | .42 | −.15 | −.09 |
| 80–85/84 | .06 | .18 | .22 | .23 | −.17| −.04| .39 | .37 | −.12 | −.03 |
| **Overall** | **.20** | **.16** | **.31** | **.35** | **.11** | **.11** | **.51** | **.39** | **−.15** | **.12** |

**Per-domain overall gender d (the single value per domain, likely what the derivation wants):**

| Domain | BHPS d | GSOEP d |
|--------|-------:|--------:|
| Extraversion      | .20  | .16 |
| Agreeableness     | .31  | .35 |
| Conscientiousness | .11  | .11 |
| Neuroticism       | .51  | .39 |
| Openness          | **−.15** | **.12** |

Note the **Openness gender effect flips sign between samples** (BHPS: men higher; GSOEP: women
higher) — the paper explicitly flags this as its one caveat. Pooling the two would give ≈ 0.

The paper reports no single pooled/averaged cross-sample d; the two-sample split above is exactly
as published. Any pooled d (e.g. averaging BHPS and GSOEP) is a downstream construction, not a
value taken from the paper.

### Education differences (bonus — also in Table 3, restricted to ages ≥ 30)

Sign convention: positive ⇒ more-educated individuals scored higher. Included for completeness;
not requested for the gender split.

| Age band | E BHPS | E GSOEP | A BHPS | A GSOEP | C BHPS | C GSOEP | N BHPS | N GSOEP | O BHPS | O GSOEP |
|----------|-------:|--------:|-------:|--------:|-------:|--------:|-------:|--------:|-------:|--------:|
| 30–39    | .20 | .18 | −.03 | −.11 | .17 | .07 | −.16 | −.27 | .51 | .19 |
| 40–49    | .27 | .18 | .04  | .06  | .34 | .21 | −.36 | −.20 | .62 | .42 |
| 50–59    | .11 | .26 | −.05 | −.07 | .14 | .11 | −.20 | −.25 | .52 | .41 |
| 60–69    | .10 | .23 | −.16 | −.12 | .05 | .18 | −.24 | −.23 | .54 | .46 |
| 70–79    | .07 | .20 | −.14 | −.01 | .07 | .16 | −.19 | −.27 | .37 | .47 |
| 80–85/84 | .03 | .09 | −.09 | .08  | .07 | .22 | −.20 | −.23 | .54 | .30 |
| **Overall** | **.22** | **.16** | **−.10** | **−.06** | **.20** | **.22** | **−.10** | **−.17** | **.60** | **.32** |

---

## Confidence / gaps

- **Table 1 grid — HIGH confidence, no gaps.** All 80 cells (2 samples × 8 bands × 5 domains,
  mean + SD each) transcribed and cross-verified against two independent renderings of the source;
  they agree exactly. The worked example reproduces z ≈ 0.110. No cell was inferred.
- **Table 3 gender d's — HIGH confidence, no gaps.** All per-band and Overall values transcribed
  from the Table 3 page and consistent with the in-text description. No cell inferred.
- **Top age band label — resolved, not inferred.** BHPS top band is **80–85**, GSOEP is **80–84**
  (source prints "80−85/84" jointly in Table 3). This is the paper's actual banding, not the
  hypothesized "80+".
- **Page numbers of the individual tables — UNAVAILABLE.** The PMC author-manuscript HTML omits
  per-table page numbers. Article-level range is 558–566; exact printed page per table not
  fabricated.
- **A pooled cross-sample gender d — NOT in the paper.** Only the BHPS/GSOEP split is published.
  Averaging is a downstream choice; flagged rather than invented.
- **Caution for the derivation:** T-scores are anchored to each sample's **age-30–34** subgroup
  (not the population grand mean), so z = 0 means "average 30–34-year-old," and z is in
  age-30–34 SD units. The Openness gender d disagrees in sign across samples (BHPS −.15 vs
  GSOEP +.12) — treat a pooled Openness gender effect as ≈ 0 / low-confidence.
