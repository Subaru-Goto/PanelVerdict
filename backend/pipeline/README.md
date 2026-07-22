# Data pipeline (stage 1 — offline)

Turns OECD statistics into the small committed joint-distribution tables the
sampler reads. **Run rarely** (only to refresh a data vintage). Design:
[`issues/006b-demographics-sampler.md`](../../issues/006b-demographics-sampler.md).

- **Not imported by `app/`** — the only link is the committed output files.
- **Stdlib only** — the builder fetches over `urllib`; no extra dependencies.
- Commit the derived `app/data/joint/<country>.csv` + `.meta.json`; nothing else.

## Run

```
uv run python -m pipeline.build_oecd US   # → app/data/joint/us.csv + us.meta.json
```

Country codes: `US`, `JP`, `DE`.

## Source

One harmonized, keyless API — [OECD SDMX](https://sdmx.oecd.org/public/rest),
queried by country code — so adding a country is a query, not a new source.

- **`age × gender × education`** — direct cross-tabs, education native ISCED-2011:
  - population: `OECD.ELS.SAE,DSD_POPULATION@DF_POP_HIST` (5-year age × sex)
  - education: `OECD.EDU.IMEP,DSD_EAG_LSO_EA@DF_LSO_NEAC_DISTR_EA` (ISCED × age × sex, 25–64)
- **income** — no OECD sex/education cross exists, so it attaches as an
  education-conditioned marginal from a fixed prior (declared imputed).

Age bands are reconciled on the 5-year population lattice; education gaps
(`<25`, `65+`) borrow the nearest observed band. Full design in the issue and
[`docs/research/oecd-demographic-data.md`](../../docs/research/oecd-demographic-data.md).
The `.meta.json` sidecar records the source dataflows, the realized income
marginal, and the declared imputations.
