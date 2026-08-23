# The backend as one process (Render builds this; deploy-targets.md holds the
# platform decision). uv's official image pins Python 3.13 to match pyproject.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /srv/backend

# Dependencies first, so a code change never re-resolves the lockfile layer.
# --no-install-project: this repo is `package = false` — there is no project to install.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Runtime code only: tests, experiments and the offline pipeline stay out of the image
# (see .dockerignore). schema.sql and the OECD joint tables ride inside app/ — the
# runtime reads them; seeding itself runs from a developer machine against Supabase.
COPY app ./app

# One worker because the free instance is small, not because it must be one:
# analyst threads live in Postgres (issue #144), so any worker or replica can
# resume any thread — this number became a tunable the day that landed.
# Render injects PORT; 8000 is the local-docker fallback.
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
