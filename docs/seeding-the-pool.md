# Seeding the persona pool

How to run `app.seed` to generate and persist the persona pool, and how to
validate quality before committing to a full run. Design: `docs/decisions/006f-persistence.md`.

## Prerequisites

A repo-root `.env` with:

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `OPENROUTER_API_KEY` (the seed makes real model calls)
- `POSTGRES_HOST` should be `localhost` (or unset — that's the default) when
  running from your terminal. If it is set to `db` (the compose service name) it
  only resolves inside the compose network, and a host-run seed can't connect.

Docker Compose already runs a pgvector-enabled Postgres (`pgvector/pgvector:pg18`).

## The CLI

```
python -m app.seed --size dev|full --seed N [--countries US,JP,DE] [--qc-sample K]
```

| flag | meaning | default |
|------|---------|---------|
| `--size` | `dev` (~200 personas) or `full` (5000) | `dev` |
| `--seed` | master RNG seed — the number all sampling is derived from. Same seed → same demographics/Big Five; a different seed → a different pool. Arbitrary value (`0` is fine). | `0` |
| `--countries` | comma-separated locales to include | `US,JP,DE` |
| `--qc-sample` | how many personas the plausibility judge scores (`0` = audit only, no judge calls) | `50` |

Re-running is **idempotent and resumable**: personas already in the DB are
skipped before assembly, so a re-run never re-pays the LLM cost.

## Steps

### 1. Start Postgres (repo root)

```bash
docker compose up -d db
docker compose ps        # wait until 'db' is healthy
```

### 2. Run the dev seed (from `backend/`)

```bash
cd backend
uv run python -m app.seed --size dev --seed 0
```

Applies the schema, samples ~200 personas, persists them, embeds the explanation
corpus, then judges a sample and prints the QC report.

No persona field is LLM-generated and nothing about a persona is embedded any
more (084/#175 retired the analyst's persona search and its vector), so the pool
is identical on every run with the same seed and costs nothing to seed — no API
key is needed for that step. Two model calls remain and are worth knowing about:
the corpus embeddings (a handful of passages, cheap) and the plausibility judge
over `--qc-sample` personas, which is a chat model and is most of the cost.
`--qc-sample 0` skips the judge. Without a key the command seeds the pool and
then exits non-zero naming the two steps it could not do.

### 3. Eyeball the personas

```bash
docker compose exec db bash -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT id, age, gender, education, income_quintile, round(openness::numeric, 2) AS o, round(neuroticism::numeric, 2) AS n FROM personas LIMIT 15;"'
```

### 4. Judge reasonableness

- **QC report:** `pass_rate` high (≈0.9+)? `mean_rating` ≥ ~4?
- **The 15 rows:** do the age/education/income combinations look like real people,
  and do the trait scores spread rather than clustering at zero?

To read a persona the way the report describes one, render its summary:

```bash
uv run python -c "from app.panel import persona_summary, FIXED_PANEL; print(persona_summary(FIXED_PANEL[0]))"
```

### 5. Decide

- **Good →** run the full pool: `uv run python -m app.seed --size full --seed 0`
  (~25× the time; resumable if interrupted).
- **Off →** the fix is in the sampled distributions or the rendering, not a
  prompt. After changing either, regenerate:

  ```bash
  docker compose exec db bash -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "TRUNCATE personas;"'
  uv run python -m app.seed --size dev --seed 0
  ```

  (Re-seeding without truncating skips the existing personas — idempotency — so
  you must truncate to regenerate after a change.)
