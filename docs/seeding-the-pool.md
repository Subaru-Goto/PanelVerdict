# Seeding the persona pool

How to run `app.seed` to generate and persist the persona pool, and how to
validate quality before committing to a full run. Design: `issues/006f-persistence.md`.

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

Applies the schema, generates ~200 personas (real interests + embeddings),
persists them, then prints the QC report. Cost ≈ a few cents.

### 3. Eyeball the actual interests (don't trust only the aggregate)

```bash
docker compose exec db bash -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT p.age, p.gender, p.education, array_agg(i.interest) FROM personas p JOIN interests i ON i.persona_id = p.id GROUP BY p.id LIMIT 15;"'
```

### 4. Judge reasonableness

- **QC report:** `pass_rate` high (≈0.9+)? `mean_rating` ≥ ~4? Any demographic
  group with a wildly low dispersion (a collapsed / caricatured group)?
- **The 15 rows:** interests *specific* (not "sports"), *plausible* for the
  age/education, and *not* obvious demographic stereotypes?

### 5. Decide

- **Good →** run the full pool: `uv run python -m app.seed --size full --seed 0`
  (~25× the dev cost/time; resumable if interrupted).
- **Off →** the fix is the prompt, not the pipeline. Tune
  `app/interests.py:build_interest_prompt`, then regenerate:

  ```bash
  docker compose exec db bash -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "TRUNCATE personas CASCADE;"'
  uv run python -m app.seed --size dev --seed 0
  ```

  (Re-seeding without truncating skips the existing personas — idempotency — so
  you must truncate to regenerate with a changed prompt.)
