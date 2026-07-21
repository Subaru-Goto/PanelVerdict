# Persona Seed Data — μ(age band, gender) and Σ for the Big Five sampler (research for ticket 006c)

*Date: 2026-07-21 · Method: primary-source retrieval (peer-reviewed psychometrics + the source PDFs/tables themselves, verified against the actual papers, not blog summaries). Feeds ticket 006c "persona sampler: draw correlated continuous Big Five vectors from `MVN(μ(age band, gender), Σ)`." Domain-level only (5 traits); NO aspects/facets.*

> **Status: numeric, load-bearing — but read the confidence flags.** Every figure below is traced to a dated primary source with N + instrument. The μ table is a *construction* (age main effect + additive gender offset) built from one source's published tables; the arithmetic is shown so 006c can re-derive or challenge it. Trait order throughout the machine-readable blocks is **`[O, C, E, A, N]`** (OCEAN).

---

## TL;DR — what 006c gets

1. **μ (mean vector, z-scored) ← Donnellan & Lucas 2008** (*Psychology and Aging*, PMC2562318). Two large national panels (BHPS N≈14k UK, GSOEP N≈21k Germany), 15-item BFI. It publishes **T-score means/SDs across 8 age bands** *and* **gender Cohen's d per domain** — the only candidate that gives fully usable per-cell numbers rather than plots/betas. **Age bands adopted: `16–19, 20–29, 30–39, 40–49, 50–59, 60–69, 70–79, 80+`** (the source's own bands).
2. **Σ (5×5 domain inter-correlation) ← van der Linden, te Nijenhuis & Bakker 2010** (*J. Research in Personality*, K=212, **N=144,117**). Meta-analytic Big Five intercorrelations across many FFM instruments. Use the **observed (uncorrected) r** matrix for sampling; corrected ρ (disattenuated) is provided as an alternative/upper bound.
3. **Bucketize ← fixed z-cutoffs at ±0.5** → LOW/MED/HIGH ≈ **30.9% / 38.3% / 30.9%** of the general population (standard-normal CDF). A ±0.43 variant gives exact terciles (33/33/33) if you want equal buckets.

**Confidence flags:** Neuroticism's age trend **conflicts between the two panels** (BHPS declines with age, GSOEP rises) → the pooled Neuroticism age slope is near-zero and **low-confidence**. Openness's *gender* offset also conflicts (BHPS men higher, GSOEP women higher) → pooled ≈ 0, **treat as no gender effect**. Everything else is directionally consistent across both panels and corroborated by the larger surveys below.

---

## 1. Mean vectors μ(age band, gender) — z-scored

### Source and why it wins

| Candidate | Sample / instrument | Gives usable per-cell means+SD? | Verdict |
|---|---|---|---|
| **Donnellan & Lucas 2008** | BHPS N≈14,039 (UK) + GSOEP N≈20,852 (DE); 15-item BFI, 7-pt | **Yes** — Table 1: T-mean+SD × 8 age bands × 5 domains × 2 samples; gender d per domain | **ADOPTED** |
| Soto, John, Gosling & Potter 2011 | N=1,267,218 (US web); 44-item BFI, ages 10–65 | No — reports standardized age *curves*/facet trends, not extractable per-band cell means | corroborating (directional) |
| Kajonius & Johnson 2019 | N=320,128 (US web); IPIP-NEO-120, 1–5 scale | Partial — overall domain M/SD only; no published sex/age cross-tab in the paper | corroborating (grand means) |
| Brandt et al. 2020 | N=1,566 (DE); 5-item BFI-S | No — measurement-invariance study; latent correlations + intercepts, no per-band M/SD | not numeric |

Soto 2011 (the largest sample) and Kajonius & Johnson agree with D&L on **direction** (Conscientiousness rises then plateaus; Openness & Extraversion decline with age; women higher on Neuroticism & Agreeableness) but neither publishes the age×gender cell means a sampler can load. D&L 2008 does, and the repo already grounds Big Five on it (`persona-attributes-grounding.md`). **Adopted for μ.**

### Conversion to z (arithmetic shown)

D&L Table 1 reports **T-scores** (M=50, SD=10) *norm-referenced to each sample's own age-30–34 subgroup*. So:

```
z_age(domain, band) = ( (T_BHPS + T_GSOEP)/2  −  50 ) / 10
```

i.e. pool the two panels by averaging their T-scores, then map T→z. **z = 0 therefore anchors to a ~30–34-year-old of average gender**, not the whole-population grand mean — a defensible "prime-age adult" reference, but flag it: these are *deviations from that anchor in age-30–34 SD units*, which are within a few % of population SDs. (Example, Openness age 16–19: T_BHPS=50.45, T_GSOEP=51.75 → z = ((50.45+51.75)/2 − 50)/10 = **+0.110**.)

**Gender** is added on top. D&L report gender didn't moderate age effects ("men and women [do not] change in distinct ways"), which *licenses an additive decomposition*. Pooled Cohen's d (women − men, averaged over both panels):

| | O | C | E | A | N |
|---|---|---|---|---|---|
| pooled d (women − men) | −0.02 | +0.11 | +0.18 | +0.33 | +0.45 |
| half-offset (±d/2) | ∓0.007 | ±0.055 | ±0.09 | ±0.165 | ±0.225 |

Then `μ(band, female) = z_age + d/2`, `μ(band, male) = z_age − d/2`. (Splitting a Cohen's d as ±d/2 around the band mean is the standard equal-variance decomposition; the sample is ~52–54% women so the true grand mean is a hair toward the female side — a <0.02 SD approximation, ignored.)

### μ table (z-scores, OCEAN)

**Age main effect (gender-averaged), pooled BHPS+GSOEP:**

| Age band | O | C | E | A | N |
|---|---|---|---|---|---|
| 16–19 | +0.110 | −0.787 | +0.209 | −0.087 | −0.037 |
| 20–29 | +0.127 | −0.248 | +0.126 | −0.017 | +0.005 |
| 30–39 | +0.001 | +0.028 | −0.009 | +0.011 | −0.002 |
| 40–49 | −0.061 | +0.102 | −0.081 | +0.061 | −0.013 |
| 50–59 | −0.075 | +0.098 | −0.173 | +0.077 | +0.005 |
| 60–69 | −0.214 | −0.027 | −0.237 | +0.077 | −0.031 |
| 70–79 | −0.403 | −0.117 | −0.345 | +0.195 | −0.119 |
| 80+ | −0.598 | −0.169 | −0.351 | +0.280 | −0.137 |

**Full age×gender μ (age effect ± gender offset):**

| Age band | Gender | O | C | E | A | N |
|---|---|---|---|---|---|---|
| 16–19 | F | +0.103 | −0.732 | +0.299 | +0.078 | +0.188 |
| 16–19 | M | +0.117 | −0.842 | +0.119 | −0.252 | −0.262 |
| 20–29 | F | +0.120 | −0.193 | +0.216 | +0.148 | +0.230 |
| 20–29 | M | +0.134 | −0.303 | +0.036 | −0.182 | −0.220 |
| 30–39 | F | −0.006 | +0.083 | +0.081 | +0.176 | +0.223 |
| 30–39 | M | +0.008 | −0.027 | −0.099 | −0.154 | −0.227 |
| 40–49 | F | −0.068 | +0.157 | +0.009 | +0.226 | +0.212 |
| 40–49 | M | −0.054 | +0.047 | −0.171 | −0.104 | −0.238 |
| 50–59 | F | −0.082 | +0.153 | −0.083 | +0.242 | +0.230 |
| 50–59 | M | −0.068 | +0.043 | −0.263 | −0.088 | −0.220 |
| 60–69 | F | −0.221 | +0.028 | −0.147 | +0.242 | +0.194 |
| 60–69 | M | −0.207 | −0.082 | −0.327 | −0.088 | −0.256 |
| 70–79 | F | −0.410 | −0.062 | −0.255 | +0.360 | +0.106 |
| 70–79 | M | −0.396 | −0.172 | −0.435 | +0.030 | −0.344 |
| 80+ | F | −0.605 | −0.114 | −0.261 | +0.445 | +0.088 |
| 80+ | M | −0.591 | −0.224 | −0.441 | +0.115 | −0.362 |

**SDs.** In z-space the per-trait SD is 1 by construction (that's what Σ's diagonal encodes). The *raw* per-cell SDs in D&L Table 1 hover around the reference SD (T-SD 9.8–13.6, i.e. ratio ≈ 0.98–1.36) — dispersion widens modestly at the age extremes (adolescents and 70+). For 006c this means: sampling with unit SD is slightly *narrow* at the tails; acceptable for v1, revisit if tail realism matters.

**Confidence flags on μ:**
- **Neuroticism age slope — LOW confidence.** BHPS Neuroticism *falls* with age, GSOEP *rises*; pooled slope ≈ 0 (see the flat N column). This is D&L's own largest cross-sample discrepancy. The *gender* effect on N (women higher, d≈0.45) is robust and consistent — keep it; distrust the N *age* gradient.
- **Openness gender — treat as ~0.** BHPS d=−0.15 (men higher), GSOEP d=+0.12 (women higher) → pooled −0.02. Don't read a gender signal into O.
- Everything else (C rises to a 40–49 peak then declines; E and O decline steadily with age; A rises with age; women higher on A, E, N) is consistent across both panels **and** matches Soto 2011 and Kajonius & Johnson directionally → **medium-high confidence, directional-plus-magnitude**.
- Whole construction is **cross-sectional** (age = cohort+age confound, not within-person aging) and anchored to a UK+DE 30–34 reference — fine for a marketing-panel *population* sampler, not for longitudinal claims.

---

## 2. Domain inter-correlation matrix Σ

### Source

**van der Linden, te Nijenhuis & Bakker (2010).** "The General Factor of Personality: A meta-analysis of Big Five intercorrelations…" *Journal of Research in Personality* 44, 315–327. Psychometric meta-analysis, **K = 212 independent samples, total N = 144,117**, across NEO-PI/NEO-FFI/BFI-family FFM instruments (2000–2008 + Digman appendix). Table 2 reports both the **observed mean r** and the **corrected ρ** (disattenuated for unreliability + range restriction). **Sign convention: Neuroticism** (not Emotional Stability) — so N correlates negatively with C/E/A/O.

Chosen over Park, Wiernik, Oh, Gonzalez-Mulé, Ones & Lee 2020 (*JAP* 105, 1490–1529, "Eeny, meeny, miney, moe") — a more recent and more sophisticated FFM-intercorrelation meta-analysis whose whole point is that intercorrelations *move with rating source and inventory* — because that paper is **paywalled (HTTP 402), so its matrix could not be verified against the source**; citing van der Linden's actually-extracted numbers is more defensible than transcribing Park et al.'s from memory. 006c should treat Park et al. 2020 as the upgrade path if the full text becomes available. This Σ **supersedes** the purely directional Donnellan & Lucas 2008 priors mentioned in earlier tickets.

### The matrix (observed r — recommended for sampling)

|  | O | C | E | A | N |
|---|---|---|---|---|---|
| **O** | 1.00 | .14 | .31 | .14 | −.12 |
| **C** | .14 | 1.00 | .21 | .31 | −.32 |
| **E** | .31 | .21 | 1.00 | .18 | −.26 |
| **A** | .14 | .31 | .18 | 1.00 | −.26 |
| **N** | −.12 | −.32 | −.26 | −.26 | 1.00 |

### Corrected ρ (disattenuated — alternative / latent-construct upper bound)

|  | O | C | E | A | N |
|---|---|---|---|---|---|
| **O** | 1.00 | .20 | .43 | .21 | −.17 |
| **C** | .20 | 1.00 | .29 | .43 | −.43 |
| **E** | .43 | .29 | 1.00 | .26 | −.36 |
| **A** | .21 | .43 | .26 | 1.00 | −.36 |
| **N** | −.17 | −.43 | −.36 | −.36 | 1.00 |

**Which to use.** The sampler draws *scores* that get rendered, so the **observed r** matches the correlation structure real measured people exhibit — use it as Σ. The corrected ρ estimates the correlation among *latent true traits* (larger because it removes measurement error); reach for it only if you deliberately want stronger cross-trait coupling. Both are **positive-definite** as 5×5 correlation matrices (all off-diagonals |r|≤.43, consistent GFP structure) → valid MVN covariance; if a future edit makes a matrix non-PD, project to the nearest PD matrix before Cholesky.

**Confidence:** high for the *structure* (huge N, consistent GFP pattern replicated across 212 samples and in Park et al. 2020). Medium for exact magnitudes — intercorrelations are known to vary ±.10ish by instrument and self- vs other-report (Park et al. 2020's central finding). The credibility intervals in van der Linden are wide for O-related pairs (e.g. O–C 80% CI (−.06, .46)). Good enough for a v1 population sampler; don't over-interpret any single off-diagonal.

---

## 3. Bucketize rule (z → LOW / MEDIUM / HIGH)

**Recommended: fixed cutoffs at z = ±0.5.**

```
z < −0.5           → LOW
−0.5 ≤ z ≤ +0.5    → MEDIUM
z > +0.5           → HIGH
```

Population coverage under the standard normal (Φ):

| Bucket | Rule | Proportion |
|---|---|---|
| LOW | z < −0.5 | Φ(−0.5) = **30.9%** |
| MEDIUM | −0.5…+0.5 | Φ(0.5)−Φ(−0.5) = **38.3%** |
| HIGH | z > +0.5 | 1−Φ(0.5) = **30.9%** |

**Justification.** The norm distribution is (by construction, z-scored) standard normal per trait, so cutoffs map directly through Φ. ±0.5 is a round, interpretable half-SD boundary that yields a near-even split with a slightly fatter, sensible MEDIUM (most people are middling on any one trait). Because μ shifts each persona's *mean* by age×gender, an individual cell's bucket mix will skew from these general-population figures — e.g. a 16–19 cell (C mean ≈ −0.79) will produce mostly LOW-Conscientiousness personas, which is the intended, grounded behavior.

**Alternatives** (state in code as a config choice):
- **±0.43 → exact terciles (33.3 / 33.3 / 33.3)** — use if you want equal-sized buckets.
- **±0.674 → 25 / 50 / 25** (quartile-anchored) — wider MEDIUM, thinner tails.

Confidence: exact (pure standard-normal arithmetic); only the *choice* of ±0.5 is a judgement call.

---

## 4. Machine-readable block (drop-in for the 006c sampler)

Trait order is `[O, C, E, A, N]`. `mu` keys are `"<age_band>|<gender>"`.

```python
TRAIT_ORDER = ["O", "C", "E", "A", "N"]  # Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism
AGE_BANDS = ["16-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80+"]

# Mean vectors μ (z-scores). Source: Donnellan & Lucas 2008 (BHPS+GSOEP, BFI),
# pooled T->z with additive gender offset (±d/2). z=0 anchors to age-30-34 reference.
MU = {
    "16-19|female": [ 0.103, -0.732,  0.299,  0.078,  0.188],
    "16-19|male":   [ 0.117, -0.842,  0.119, -0.252, -0.262],
    "20-29|female": [ 0.120, -0.193,  0.216,  0.148,  0.230],
    "20-29|male":   [ 0.134, -0.303,  0.036, -0.182, -0.220],
    "30-39|female": [-0.006,  0.083,  0.081,  0.176,  0.223],
    "30-39|male":   [ 0.008, -0.027, -0.099, -0.154, -0.227],
    "40-49|female": [-0.068,  0.157,  0.009,  0.226,  0.212],
    "40-49|male":   [-0.054,  0.047, -0.171, -0.104, -0.238],
    "50-59|female": [-0.082,  0.153, -0.083,  0.242,  0.230],
    "50-59|male":   [-0.068,  0.043, -0.263, -0.088, -0.220],
    "60-69|female": [-0.221,  0.028, -0.147,  0.242,  0.194],
    "60-69|male":   [-0.207, -0.082, -0.327, -0.088, -0.256],
    "70-79|female": [-0.410, -0.062, -0.255,  0.360,  0.106],
    "70-79|male":   [-0.396, -0.172, -0.435,  0.030, -0.344],
    "80+|female":   [-0.605, -0.114, -0.261,  0.445,  0.088],
    "80+|male":     [-0.591, -0.224, -0.441,  0.115, -0.362],
}

# Domain inter-correlation matrix Σ (observed r). Source: van der Linden et al. 2010
# (K=212, N=144,117). Neuroticism sign convention. Unit diagonal => also the covariance
# in z-space. Positive-definite; safe for Cholesky/MVN.
SIGMA = [
    [ 1.00,  0.14,  0.31,  0.14, -0.12],  # O
    [ 0.14,  1.00,  0.21,  0.31, -0.32],  # C
    [ 0.31,  0.21,  1.00,  0.18, -0.26],  # E
    [ 0.14,  0.31,  0.18,  1.00, -0.26],  # A
    [-0.12, -0.32, -0.26, -0.26,  1.00],  # N
]

# Alternative: corrected (disattenuated) ρ — stronger coupling, latent-construct estimate.
SIGMA_CORRECTED = [
    [ 1.00,  0.20,  0.43,  0.21, -0.17],
    [ 0.20,  1.00,  0.29,  0.43, -0.43],
    [ 0.43,  0.29,  1.00,  0.26, -0.36],
    [ 0.21,  0.43,  0.26,  1.00, -0.36],
    [-0.17, -0.43, -0.36, -0.36,  1.00],
]

# Render-time bucketize on the sampled z-scale. General-pop coverage: 30.9/38.3/30.9%.
BUCKET_CUTOFFS = {"low": -0.5, "high": 0.5}  # z<low -> LOW ; low<=z<=high -> MEDIUM ; z>high -> HIGH
```

---

## Sources (primary, verified against the source document)

- **μ (adopted):** Donnellan, M. B., & Lucas, R. E. (2008). *Age differences in the Big Five across the life span: Evidence from two national samples.* **Psychology and Aging, 23(3), 558–566.** PMC2562318. — BHPS N≈14,039 (UK) + GSOEP N≈20,852 (DE), 15-item BFI, 7-pt. Table 1 (T-mean/SD × 8 age bands × 5 domains × 2 samples) and gender Cohen's d extracted directly.
- **Σ (adopted):** van der Linden, D., te Nijenhuis, J., & Bakker, A. B. (2010). *The General Factor of Personality: A meta-analysis of Big Five intercorrelations and a criterion-related validity study.* **Journal of Research in Personality, 44, 315–327.** K=212, N=144,117. Table 2 (observed r + corrected ρ) extracted directly from the PDF.
- **Corroborating (directional) for μ:** Soto, C. J., John, O. P., Gosling, S. D., & Potter, J. (2011). *Age differences in personality traits from 10 to 65.* **JPSP, 100(2), 330–348.** N=1,267,218, 44-item BFI. — direction of age trends only; no extractable per-band cells.
- **Corroborating (grand means) for μ:** Kajonius, P. J., & Johnson, J. A. (2019). *Assessing the structure of the FFM (IPIP-NEO-120) in the public domain.* **Europe's Journal of Psychology / PMC7871748.** N=320,128, IPIP-NEO-120, 1–5 scale. Overall domain M/SD (1–5, facet 4–20): reference only; no age×gender cross-tab published.
- **Considered, not numeric:** Brandt, N. D., et al. (2020). *Personality across the lifespan.* **European Journal of Psychological Assessment.** N=1,566, 5-item BFI-S (Germany) — measurement-invariance study; no per-band M/SD.
- **Σ upgrade path (paywalled, not extracted):** Park, H. H., Wiernik, B. M., Oh, I.-S., Gonzalez-Mulé, E., Ones, D. S., & Lee, Y. (2020). *Meta-analytic five-factor model personality intercorrelations: Eeny, meeny, miney, moe…* **Journal of Applied Psychology, 105(12), 1490–1529.** — more recent; shows intercorrelations vary by rating source/inventory. Cite as the future replacement for Σ once full text is accessible.

---

## Applicability under the multi-region decision (2026-07-21)

Per the 001 amendment (2026-07-21), v1 seeds three countries (Japan, US, Germany) with **decision (i): country does not condition the Big Five μ.** So the μ / Σ tables above are used as **shared age/gender contrasts across all three countries** — not re-derived per country. Rationale (reference-group effect; ~universal age/gender structure; weak per-country data) is recorded in 001 and 006c.

- The **Donnellan & Lucas 2008** μ is the shared contrast source. (Its GSOEP half is German and its BHPS half UK — i.e. it is *already* a Western-panel source; using it as the shared contrast is consistent, not a stretch.)
- **BFI-2-J** and the US samples (Soto 2011, Kajonius & Johnson) are **validation checks** that the structure + age direction replicate in Japan/US — not per-country μ inputs.
- What *does* vary by country: **demographics** (national census — 006b) and **interests** (culturally-conditioned synthesis — 006d). Σ and the age/gender μ contrasts are country-agnostic.
