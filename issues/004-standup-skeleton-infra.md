---
title: "Stand up project skeleton + local infra"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: subaru
status: done
---

## Goal

Create the runnable skeleton everything else sits on:

- **monorepo layout — `/frontend` + `/backend`** at the repo root (decided 2026-07-16),
- **FastAPI + LangGraph** backend,
- **Next.js + Tailwind** frontend,
- **Postgres + pgvector** via Docker for local dev,
- OpenRouter + LangSmith env wiring (populate from `.example.env`).

Done when a hello-world request flows through the whole stack: frontend → API → DB → back.

## Consciously deferred (recorded 2026-07-16, from code review)

- **LangGraph dependency** — not installed in the skeleton; it belongs with the first ticket that actually uses it (**010 — orchestrator graph**). "FastAPI + LangGraph backend" in the Goal reads as the target architecture, not a skeleton requirement. **Resolved 2026-07-27:** 010 decided against it for v1, so the dependency is never installed — deferring it turned out to be what kept the choice open long enough to make it on evidence.
- **OpenRouter + LangSmith env wiring** — deferred to the first ticket that makes an LLM call (**003/005-era**); the pydantic-settings pattern in `config.py` is the template to extend.

## Delivered so far

- Backend half (units 1–3): monorepo `backend/`, FastAPI `/health` → Postgres check, docker-compose Postgres 18 + **pgvector (extension enabled + auto-init SQL in `db/init/`)**, no-hardcode env config from the repo-root `.env`. Verified live: `{"status":"ok","db":"up"}`; `vector` extension 0.8.5 confirmed.
- Frontend half (units 4–5): Next.js 16 App Router scaffold (TypeScript, Tailwind v4), client-side `HealthCheck` component (`app/components/`) that fetches `GET /health` from the browser, CORS middleware allowing the configured frontend origin, API base URL from `NEXT_PUBLIC_API_URL`.
- **Done criterion met** — full stack verified live end to end: browser → API → DB → back renders `API: ok · DB: up`.