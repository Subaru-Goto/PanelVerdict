"""Stage 1 (US) — build the US joint from ACS PUMS. Exact; no IPF.

Run offline: `uv run --group pipeline python -m pipeline.build_us`
Reads `pipeline/raw/us_pums.csv` (see README), writes
`app/data/joint/us.csv` + `us.meta.json`.

The US path is the reference case: because PUMS is individual microdata, the
joint is just a weighted tabulation of real records — every correlation is
preserved by construction, and the result is exact (fidelity: all pairs observed).
"""

# TODO imports: pandas as pd; pathlib.Path; json; hashlib (raw checksum);
#   app.schemas EducationLevel for the mapping target.

# --- paths ---
# TODO: RAW = Path(__file__).parent / "raw" / "us_pums.csv"
# TODO: OUT_CSV  = Path(__file__).parents[1] / "app" / "data" / "joint" / "us.csv"
# TODO: OUT_META = OUT_CSV.with_suffix(".meta.json")

# --- PUMS value → our schema mappings ---
# TODO: SCHL (24 PUMS attainment codes) → EducationLevel
#       (≤ code X → below_secondary; HS/some-college → secondary; bachelor+ → tertiary)
# TODO: SEX (1/2) → "male"/"female"
# TODO: age_band(age: int) -> str  — the D&L bands: 18-19, 20-29, ... , 80+


def load_pums():
    """Read the raw ACS PUMS person file, keeping only AGEP/SEX/PINCP/SCHL/PWGTP."""
    # TODO: pd.read_csv(RAW, usecols=[...]); return the frame
    ...


def assign_income_quintile(df):
    """Add an `income_quintile` (1–5) column: PWGTP-weighted percentiles of PINCP.

    Within-US quintile — the cut points are the weighted 20/40/60/80th percentiles
    of PINCP; each person maps to the band they fall in.
    """
    # TODO: compute the four weighted cut points from (PINCP, PWGTP)
    # TODO: bucket each PINCP into 1..5; return df with the new column
    ...


def build() -> None:
    """PUMS → aggregate → quintiles → `us.csv` + `us.meta.json`."""
    # TODO: df = load_pums()
    # TODO: keep AGEP >= 18
    # TODO: map SEX → gender, SCHL → education, AGEP → age_band
    # TODO: df = assign_income_quintile(df)
    # TODO: group by (age_band, gender, education, income_quintile), sum PWGTP → weight
    # TODO: normalize weight to sum 1.0; sort for a stable diff
    # TODO: write OUT_CSV (columns: age_band,gender,education,income_quintile,weight)
    # TODO: write OUT_META — source, table id, vintage, retrieved, raw_checksum,
    #       build="pipeline/build_us.py", fidelity={"exact": true, "imputed_independent": []}
    ...


if __name__ == "__main__":
    build()
