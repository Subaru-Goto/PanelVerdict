# National time-use tables (retired data)

Six tables of leisure participation rates by country, gender and age band, built
from national time-use surveys in July 2026 and **not used by any code**.

They live here rather than under `backend/app/data/` on purpose: that directory
means "the app loads this", and nothing loads these. See
[issues/006i](../../decisions/006i-leisure-profiles.md) for why leisure was closed
— briefly, no evidence a leisure field moves a headline vote, and each new country
cost a bespoke extraction.

## Why they were kept at all

Germany and Japan are re-pullable from their APIs, so their value is only saved
effort. **The US table is not.** BLS blocks scripted clients at the edge, publishes
no machine-readable copy of ATUS Table A-1, and does not publish participation by
age at all — so `us.csv` was transcribed by hand from a PDF, cross-checked against
the news-release tables, and every band carries the gender-only figure. Re-creating
it means someone reading that PDF again.

## Provenance

Each `.meta.json` carries the country's declarations: what was combined and how,
what was published but deliberately excluded, and where a category means something
narrower than in the other two countries. Read it before reusing a number — the
scope differences are real and the sidecar is the only place they are recorded.

`pipeline/build_leisure.py` produced `de.csv` and `jp.csv` from the Eurostat and
e-Stat APIs. It was deleted along with its tests and fixtures when 006i closed;
recover it from git history (`git log --diff-filter=D -- backend/pipeline/build_leisure.py`)
if these ever need rebuilding.
