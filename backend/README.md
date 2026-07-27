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
