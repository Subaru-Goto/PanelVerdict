---
title: "Stand up project skeleton + local infra"
labels: [wayfinder:task]
parent: 000-map
blocked_by: []
assignee: subaru
status: open
---

## Goal

Create the runnable skeleton everything else sits on:

- **monorepo layout — `/frontend` + `/backend`** at the repo root (decided 2026-07-16),
- **FastAPI + LangGraph** backend,
- **Next.js + Tailwind** frontend,
- **Postgres + pgvector** via Docker for local dev,
- OpenRouter + LangSmith env wiring (populate from `.example.env`).

Done when a hello-world request flows through the whole stack: frontend → API → DB → back.