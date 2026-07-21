# Data pipeline (stage 1 — offline)

Turns raw national statistics into the small committed joint-distribution tables
the sampler reads. **Run rarely** (only when a data vintage updates). Design:
[`issues/006b-demographics-sampler.md`](../../issues/006b-demographics-sampler.md).

- **Not imported by `app/`** — the only link is the committed output files.
- **Deps** (`pandas`) live in the `pipeline` group, not runtime: `uv sync --group pipeline`.
- **`raw/` is gitignored** — download sources there manually per the recipes below; commit only the derived `app/data/joint/<country>.csv` + `.meta.json`.

## Run

```
uv run --group pipeline python -m pipeline.build_us   # → app/data/joint/us.csv + us.meta.json
```

## Acquisition recipes

Each recipe pins the exact source so a rebuild is reproducible. Record source +
table id + vintage + retrieval date + raw-file checksum in the output `.meta.json`.

### US — ACS PUMS (build order: first; exact, no IPF)

- **Source:** U.S. Census Bureau, ACS Public Use Microdata Sample (person file).
  `https://www.census.gov/programs-surveys/acs/microdata/access.html`
- **Vintage:** TODO — confirm (e.g. ACS 2022 1-year).
- **Columns to keep:** `AGEP` (age), `SEX`, `PINCP` (personal income), `SCHL`
  (education attainment), `PWGTP` (person weight).
- **Save as:** `raw/us_pums.csv`
- **License:** U.S. federal public-domain-style; no registration.

### DE — Destatis (build order: second; income via IPF)

TODO — Destatis GENESIS cross-tabs (age×gender×education; income brackets;
Gender Pay Gap marginal). See `docs/research/demographic-sources.md`.

### JP — e-Stat (build order: third; IPF)

TODO — e-Stat census table 62-2 (age×gender×education) + Employment Status
Survey income table. See `docs/research/demographic-sources.md`.
