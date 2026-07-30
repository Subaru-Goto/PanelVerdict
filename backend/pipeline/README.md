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

## Add a country

For an OECD member with complete data, it's three edits + one command — no new
logic (`parse → combine → attach_income → rake` all run by country code):

1. `Locale` enum (`app/schemas.py`) — add the member, e.g. `FR = "FR"`.
2. `COUNTRY_CULTURE_TAG` (`app/schemas.py`) — map it, e.g. `Locale.FR: CultureTag.WESTERN`.
3. `_REF_AREA` (`build_oecd.py`) — add its OECD 3-letter code, e.g. `Locale.FR: "FRA"`.
4. `uv run python -m pipeline.build_oecd FR` → commit the generated `fr.csv` + `fr.meta.json`.

Income and Big Five cost nothing per country: income is a country-agnostic prior
raked per-country automatically; Big Five is country-agnostic norms.

Three cases need more than the enum:

- **Non-OECD country** — may be absent from the dataflows; the build fails. Needs
  the World Bank PIP fallback (designed, not yet implemented).
- **Partial attainment + dissimilar structure** — a country reporting only part of
  the ISCED split auto-borrows from `_SPLIT_PEERS` (US, DE). Those are
  high-completion peers; a high-below-secondary country (e.g. MX, TR) needs a
  curated peer set, and the fail-loud guard will stop a build whose peers can't
  supply a missing level.
- **Culture outside western/asian** — `CultureTag` has only those two; a country
  that is cleanly neither needs a new value (a modeling decision, not a mechanical add).
