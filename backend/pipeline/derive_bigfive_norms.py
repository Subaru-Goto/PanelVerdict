"""Derive the committed Big Five norms artifact from cited primary-source inputs.

Turns Donnellan & Lucas 2008 Table 1 (raw T-scores) + Table 3 (gender d's) into
the z-scored μ vectors, and pairs them with the van der Linden 2010 Σ, writing
`app/data/bigfive_norms.json` (loaded at runtime by app/bigfive.py).

Run: `python -m pipeline.derive_bigfive_norms`. Raw inputs transcribed in
`docs/research/donnellan-lucas-2008-table1.md` (verified against PMC2562318).
"""

import json
from pathlib import Path

# Table 1 publishes domains in this column order; μ is emitted in TRAIT_ORDER.
_TABLE1_ORDER = ["E", "A", "C", "N", "O"]
TRAIT_ORDER = ["O", "C", "E", "A", "N"]
BANDS = ["16-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70-79", "80+"]

# Donnellan & Lucas 2008 Table 1 — T-score means (T-scale: mean 50, SD 10),
# columns [E, A, C, N, O]. The
# two source panels: BHPS = British Household Panel Study (UK); GSOEP = German
# Socio-Economic Panel (Germany). Top band is the paper's 80-85 (BHPS) / 80-84
# (GSOEP), both taken as our "80+".
_T_BHPS = {
    "16-19": [53.01, 48.61, 42.76, 50.47, 50.45],
    "20-29": [51.58, 50.00, 47.88, 50.10, 51.08],
    "30-39": [49.70, 50.43, 50.35, 49.92, 49.79],
    "40-49": [48.54, 50.91, 50.82, 49.39, 48.64],
    "50-59": [47.47, 51.32, 50.80, 48.99, 48.06],
    "60-69": [46.98, 50.98, 49.24, 47.87, 46.28],
    "70-79": [45.56, 51.43, 47.20, 46.25, 44.27],
    "80+": [45.41, 51.44, 46.77, 46.52, 42.47],
}
_T_GSOEP = {
    "16-19": [51.17, 49.64, 41.49, 48.80, 51.75],
    "20-29": [50.94, 49.65, 47.15, 49.99, 51.46],
    "30-39": [50.12, 49.79, 50.22, 50.04, 50.23],
    "40-49": [49.84, 50.31, 51.22, 50.36, 50.15],
    "50-59": [49.08, 50.21, 51.16, 51.10, 50.43],
    "60-69": [48.27, 50.56, 50.23, 51.51, 49.43],
    "70-79": [47.54, 52.46, 50.46, 51.38, 47.66],
    "80+": [47.57, 54.16, 49.84, 50.74, 45.56],
}

# Table 3 — overall gender Cohen's d per domain (positive = women higher),
_D_BHPS = [0.20, 0.31, 0.11, 0.51, -0.15]
_D_GSOEP = [0.16, 0.35, 0.11, 0.39, 0.12]

# van der Linden et al. 2010 Table 2 — observed r, in TRAIT_ORDER [O,C,E,A,N].
_SIGMA = [
    [1.0, 0.14, 0.31, 0.14, -0.12],
    [0.14, 1.0, 0.21, 0.31, -0.32],
    [0.31, 0.21, 1.0, 0.18, -0.26],
    [0.14, 0.31, 0.18, 1.0, -0.26],
    [-0.12, -0.32, -0.26, -0.26, 1.0],
]

_TO_TRAIT_ORDER = [_TABLE1_ORDER.index(t) for t in TRAIT_ORDER]


def _reorder(values: list[float]) -> list[float]:
    """Reorder a [E,A,C,N,O] vector into TRAIT_ORDER [O,C,E,A,N]."""
    return [values[i] for i in _TO_TRAIT_ORDER]


def derive() -> dict:
    """Compute the norms artifact (μ + Σ + provenance) from the raw inputs.

    Per age band × domain: pool the two samples' T-scores and map to z,
    `z = ((T_BHPS + T_GSOEP)/2 - 50)/10`; pool the two samples' gender d and split
    `μ(female)=z+d/2`, `μ(male)=z-d/2`. Σ is used as published (no derivation).

    The `- 50` and `/ 10` come from the T-score scale, not the data: T-scores are
    defined with mean 50 and SD 10 (T = 50 + 10z), so subtracting the mean (50) and
    dividing by the SD (10) converts a T-score to a standard z-score.
    """
    mu: dict[str, list[float]] = {}
    d = [(_D_BHPS[i] + _D_GSOEP[i]) / 2 for i in range(5)]
    for band in BANDS:
        # (T - 50)/10: recenter by the T-mean (50), rescale by the T-SD (10) -> z
        z = [((_T_BHPS[band][i] + _T_GSOEP[band][i]) / 2 - 50) / 10 for i in range(5)]
        female = _reorder([round(z[i] + d[i] / 2, 4) for i in range(5)])
        male = _reorder([round(z[i] - d[i] / 2, 4) for i in range(5)])
        mu[f"{band}|female"] = female
        mu[f"{band}|male"] = male
    return {
        "provenance": {
            "mu_source": "Donnellan & Lucas 2008, Psychology and Aging 23(3):558-566, Tables 1+3 (BHPS = British Household Panel Study, UK, N~14039; GSOEP = German Socio-Economic Panel, Germany, N~20852; 15-item BFI)",
            "mu_derivation": "per age band x domain: z = ((T_BHPS + T_GSOEP)/2 - 50)/10; gender split mu(female)=z+d/2, mu(male)=z-d/2 from pooled per-domain Cohen's d",
            "sigma_source": "van der Linden, te Nijenhuis & Bakker 2010, J. Research in Personality 44:315-327, Table 2 observed r (K=212, N=144117); Neuroticism sign convention",
            "trait_order": TRAIT_ORDER,
            "note": "Shared across all countries (001 decision (i): country does not condition Big Five mu). Raw inputs: docs/research/donnellan-lucas-2008-table1.md. Regenerate: python -m pipeline.derive_bigfive_norms.",
        },
        "mu": mu,
        "sigma": _SIGMA,
    }


_ARTIFACT = Path(__file__).parents[1] / "app" / "data" / "bigfive_norms.json"


if __name__ == "__main__":
    _ARTIFACT.write_text(json.dumps(derive(), indent=2) + "\n")
    print(f"wrote {_ARTIFACT.relative_to(Path.cwd())}")
