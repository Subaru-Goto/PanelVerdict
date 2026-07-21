"""Stage 1 (US) — build the US joint from ACS PUMS. Exact; no IPF.

Run offline: `uv run --group pipeline python -m pipeline.build_us`
Reads `pipeline/raw/us_pums.csv` (see README), writes
`app/data/joint/us.csv` + `us.meta.json`.

Because PUMS is individual microdata, the joint is just a weighted tabulation of
real records — every correlation is preserved by construction (fidelity: exact).
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from app.schemas import EducationLevel

_RAW = Path(__file__).parent / "raw" / "us_pums.csv"
_OUT_CSV = Path(__file__).parents[1] / "app" / "data" / "joint" / "us.csv"
_OUT_META = _OUT_CSV.with_suffix(".meta.json")

# Must match the ACS release actually downloaded into raw/ — recorded in the meta.
_VINTAGE = "acs-2022-1yr"

_GENDER = {1: "male", 2: "female"}  # ACS PUMS SEX codes
_DIMS = ["age_band", "gender", "education", "income_quintile"]


def _age_band(age: int) -> str:
    """Map an age to the shared D&L band (the same bands Big Five conditions on)."""
    if age >= 80:
        return "80+"
    if age <= 19:
        return "18-19"
    decade = age // 10 * 10
    return f"{decade}-{decade + 9}"


def _education_level(schl: int) -> str:
    """Collapse the 24 PUMS SCHL attainment codes onto our 3 ISCED levels."""
    if schl <= 15:  # through "12th grade, no diploma"
        return EducationLevel.BELOW_SECONDARY.value
    if schl <= 20:  # HS diploma / GED / some college / associate's
        return EducationLevel.SECONDARY.value
    return EducationLevel.TERTIARY.value  # bachelor's and above (codes 21–24)


def load_pums() -> pd.DataFrame:
    """Read the raw ACS PUMS person file, keeping only the fields we use."""
    return pd.read_csv(_RAW, usecols=["AGEP", "SEX", "PINCP", "SCHL", "PWGTP"])


def assign_income_quintile(df: pd.DataFrame) -> pd.Series:
    """Rank each person into a within-US income quintile (1–5), PWGTP-weighted.

    ADJINC (the PUMS inflation factor) is a constant scaler, so it can't change
    the ranking — we skip it and rank raw PINCP.
    """
    income = df["PINCP"].to_numpy()
    weight = df["PWGTP"].to_numpy(dtype=float)
    order = np.argsort(income)
    cum_weight = np.cumsum(weight[order])
    targets = np.array([0.2, 0.4, 0.6, 0.8]) * cum_weight[-1]
    cutoffs = np.interp(targets, cum_weight, income[order])
    quintile = np.searchsorted(cutoffs, income, side="right") + 1
    return pd.Series(quintile, index=df.index)


def build() -> None:
    """PUMS → weighted tabulation over `_DIMS` → `us.csv` + `us.meta.json`."""
    df = load_pums()
    df = df[df["AGEP"] >= 18].dropna(subset=["PINCP"])
    df = df.assign(
        age_band=df["AGEP"].map(_age_band),
        gender=df["SEX"].map(_GENDER),
        education=df["SCHL"].map(_education_level),
        income_quintile=assign_income_quintile(df),
    )
    joint = df.groupby(_DIMS, observed=True)["PWGTP"].sum().reset_index(name="weight")
    joint["weight"] = joint["weight"] / joint["weight"].sum()
    joint = joint.sort_values(_DIMS).reset_index(drop=True)

    _OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    joint.to_csv(_OUT_CSV, index=False, float_format="%.8g")
    _write_meta()


def _raw_checksum() -> str:
    h = hashlib.sha256()
    with _RAW.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _write_meta() -> None:
    """Sidecar provenance the 006g QC and humans read. US is exact — nothing imputed."""
    meta = {
        "country": "US",
        "source": "US Census Bureau — ACS PUMS (person file)",
        "vintage": _VINTAGE,
        "built": date.today().isoformat(),
        "raw_checksum": _raw_checksum(),
        "build": "pipeline/build_us.py",
        "fidelity": {"exact": True, "observed_pairs": "all", "imputed_independent": []},
    }
    _OUT_META.write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    build()
