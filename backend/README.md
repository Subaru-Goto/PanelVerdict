# PanelVerdict — backend

FastAPI service (later: the orchestrator + panel pipeline).

## Local dev

```bash
# from repo root: start Postgres + pgvector
docker compose up -d

# from backend/: install deps and run the API
uv sync
uv run fastapi dev app/main.py
```

`GET /health` returns `{"status": "ok", "db": "up|down"}` — the `db` field proves the API can reach Postgres.

**pgvector:** `db/init/01-pgvector.sql` enables the extension automatically on a *fresh* data volume. If your volume predates it, enable once by hand:

```bash
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE EXTENSION IF NOT EXISTS vector;"'
```

## Config

Read from the **repo-root `.env`** (see `../.example.env` for the keys): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`. These are **required** — there is no default. `config.py` assembles the connection URL from them, and `docker-compose.yml` reads the same variables, so the credentials live in exactly one place with nothing hardcoded.

## Red-team the chat channel (on demand, paid)

`experiments/red_team/` runs promptfoo's generated attacks against a **local**
backend — never the deployment. Record and rates: `docs/research/chat-red-team.md`.
Every run costs OpenRouter money; say the number before starting one.

```bash
# from backend/
# 1. a scratch database, so the run never touches real rows
docker run -d --name pv-redteam -e POSTGRES_PASSWORD=scratch -e POSTGRES_DB=panelverdict \
  -p 55432:5432 pgvector/pgvector:pg18
export POSTGRES_USER=postgres POSTGRES_PASSWORD=scratch POSTGRES_DB=panelverdict \
  POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432
uv run python -m app.seed --schema-only
uv run python -m app.seed --corpus-only            # 15 embeddings, under a cent
export TEST_ID=$(uv run python -m experiments.red_team.seed_target)

# 2. the backend in production shape, sign-in off, the chat turn caps lifted.
#    `off` is a word on purpose: a blank URL still refuses to boot. The shared
#    secret is a throwaway for this loopback process, not a real one.
SUPABASE_PROJECT_URL=off API_SHARED_SECRET=redteam-local \
  CHAT_TURNS_PER_THREAD_PER_DAY=100000 CHAT_TURNS_PER_CALLER_PER_DAY=100000 \
  uv run uvicorn app.main:app --port 8000

# 3. the run (smoke first: ten attacks, no strategies). promptfoo is a
#    third-party process fetched by npx: hand it the one key it needs, in a
#    git-ignored file, never the whole .env. Remote generation asks once for
#    an email to register with promptfoo.
cd experiments/red_team
grep '^OPENROUTER_API_KEY=' ../../../.env > .env.redteam
export RED_TEAM_KEY=redteam-local PROMPTFOO_DISABLE_TELEMETRY=1
npx promptfoo@0.122.2 redteam run -c smoke.yaml --env-file .env.redteam \
  -o ../out/red-team/smoke.tests.yaml -j 2 --no-cache --force
npx promptfoo@0.122.2 redteam run -c full.yaml --env-file .env.redteam \
  -o ../out/red-team/full.tests.yaml -j 4 --no-cache --force

# 4. read it: every attack, reply and verdict in a local browser UI —
#    do not use its Share button, that uploads the replies to promptfoo's cloud
npx promptfoo@0.122.2 view -y
# ...or the three rates and every fail on the terminal, from the eval id the run printed
cd ../.. && uv run python -m experiments.red_team.analyze <eval-id> --fails
```

Afterwards: `docker rm -f pv-redteam` and `rm experiments/red_team/.env.redteam`. Outputs land in `experiments/out/` (git-ignored);
promptfoo keeps its own store in `~/.promptfoo`.
