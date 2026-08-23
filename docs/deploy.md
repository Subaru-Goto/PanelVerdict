# Deploying PanelVerdict — the $5/month shape

The platform decision and every sourced number live in
[research/deploy-targets.md](research/deploy-targets.md); ticket
[087/#180](https://github.com/Subaru-Goto/PanelVerdict/issues/180) carries the build.
This is the operator's checklist — what to click, in what order, and why the order
matters. **Ship dark**: the URL stays unannounced until auth (#158), rate limits (#143)
and the cost-ceiling implementation hold.

## The shape

| piece | platform | $/mo |
|---|---|---|
| Next.js frontend | Vercel Hobby | 0 |
| FastAPI backend (one always-on service) | Railway Hobby | 5 |
| Postgres + pgvector + auth | Supabase free tier | 0 |
| CI + daily keep-alive | GitHub Actions (this repo) | 0 |

## 1 — Supabase (do first: everything else needs its connection string)

1. Create a project (region: EU, matching the developer). Save the database password.
2. Get the **direct** connection string (Connect → Direct connection — the IPv6 one,
   *not* the pooler). The repo talks psycopg3 with prepared statements, so the
   transaction pooler is never an option; the session pooler is the IPv4 fallback only.
3. Apply the schema and seed from your machine (paid embedding calls happen here, once):
   set the `POSTGRES_*` values in `.env` to the Supabase project, then
   `uv run python -m app.seed --size full`.

## 2 — Railway (the backend)

1. New project → deploy from this GitHub repo, root directory `backend/` (the
   `Dockerfile` there is the build recipe — one worker by design, see its comment).
2. **Before first deploy finishes: Settings → Networking → Enable Outbound IPv6.**
   Without it, Supabase direct connections fail with a bare `ENETUNREACH` — this is the
   single most likely trap in the whole setup.
3. Variables — mark the secrets **sealed** (write-only):
   - `OPENROUTER_API_KEY` *(sealed)*
   - `POSTGRES_USER`, `POSTGRES_PASSWORD` *(sealed)*, `POSTGRES_DB`, `POSTGRES_HOST`,
     `POSTGRES_PORT` — from the Supabase direct string
   - `PROFILE` — leave unset for `dev` while dark; `prod` is a deliberate act
   - `FRONTEND_ORIGIN` — the Vercel URL, once step 3 exists (CORS)
4. Generate a public domain for the service; note it — it is the API URL.

## 3 — Vercel (the frontend)

1. Import the repo, root directory `frontend/` (Next.js is auto-detected).
2. One environment variable: `NEXT_PUBLIC_API_URL` = the Railway domain (no trailing
   slash).
3. Deploy; then go back to Railway and set `FRONTEND_ORIGIN` to the Vercel URL.

## 4 — GitHub (already in the repo)

- CI (`.github/workflows/ci.yml`) runs both suites on every push — nothing to configure.
- Keep-alive (`.github/workflows/keepalive.yml`) pings `/health` daily, which runs a real
  Postgres check — one green run per day keeps the Supabase free tier awake *and* smoke
  tests the stack. Activate it by setting the repository **variable**
  `DEPLOY_HEALTH_URL` to the Railway domain; until then it skips quietly.

## Done-when checks (ticket 087's bar)

- `curl <railway-url>/health` → `{"status":"ok","db":"up"}`
- the Vercel page runs a dev-profile evaluate end to end, and an analyst turn streams
- the keep-alive workflow has one green scheduled run
- the Railway bill reads $5.00
