# Deploying PanelVerdict — the $0/month shape

The platform decision and every sourced number live in
[research/deploy-targets.md](research/deploy-targets.md) (see its 2026-08-23 amendment:
the budget is zero); ticket
[087/#180](https://github.com/Subaru-Goto/PanelVerdict/issues/180) carries the build.
This is the operator's checklist — what to click, in what order, and why the order
matters. **Ship dark**: the URL stays unannounced until auth (#158) and the
cost-ceiling implementation hold — the edge secret and rate limits landed with #143.
Unannounced, never secret (#187): the backend URL is guessable by construction (a
Render URL derives from its service name), so dark means *unlinked*, and the actual
protection is the edge gate plus the rest of the safety spine. Since #143 the browser
talks only to the frontend's own `/api/*` proxy routes — the backend URL and the edge
secret live in server-side env, never in the client bundle. Nothing in this repo, its
tracker, or its workflow logs may print the live URL.

**The guided way: `bash scripts/deploy-wizard.sh`** — it walks these exact steps,
opens each dashboard, captures the values into `.env.deploy` (gitignored; re-runs
remember), runs the seed with those values without touching your local `.env`, and
verifies each stage with a curl. The sections below are the same procedure in prose.

## The shape

| piece | platform | $/mo |
|---|---|---|
| Next.js frontend | Vercel Hobby | 0 |
| FastAPI backend (Docker, kept warm) | Render free web service | 0 |
| Postgres + pgvector + auth | Supabase free tier | 0 |
| keep-warm ping, every 12 min | cron-job.org | 0 |
| CI + daily loud health check | GitHub Actions (this repo) | 0 |

No payment card anywhere. The trade, stated plainly: Render free spins down after 15
idle minutes and wakes in ~1 minute. The 12-minute ping keeps it warm almost always;
analyst threads live in Postgres (#144), so a spin-down that does slip through costs
the ~1-minute wake and nothing else — conversations resume where they left off.

## 1 — Supabase (do first: everything else needs its connection values)

1. Create a project (region: EU, matching the developer). Save the database password.
2. Get the **session pooler** connection (Connect → Session pooler). Render is
   IPv4-only, and Supabase's direct connections are IPv6-only — the session pooler is
   the IPv4 door. Note the pooler host (`aws-…pooler.supabase.com`), port `5432`, and
   the username (`postgres.<project-ref>` — the ref suffix matters). **Never the
   transaction pooler** (port 6543): psycopg3 uses prepared statements.
3. Apply the schema and seed from your machine (paid embedding calls happen here, once):
   run `uv run python -m app.seed --size full` from `backend/` with the pooler values
   as environment overrides (the wizard does this for you).

**Re-run the schema step on any deploy that adds a table.** `apply_schema` is
idempotent and the seed resumes, so re-running costs nothing when the pool is already
there — but nothing re-runs it for you, and a table the code expects and the database
lacks is a 500 on every request that touches it. `request_ledger` (045/#143) is the
first case: without it both paid endpoints fail. `spend_ledger` (064/#192, the global
daily cap) is the second, with the same symptom. Re-running the same seed command
creates them.

## 2 — Render (the backend)

1. **Create a new workspace for PanelVerdict** — the 750 free hours/month are *per
   workspace*, exhaustion suspends *all* of a workspace's free services until the next
   month, and one kept-warm service uses ~744. Any other kept-warm free project must
   live in a different workspace. After creating it, check the workspace's free-hours
   meter shows its own full allowance.
2. In that workspace: New → Web Service → this GitHub repo, root directory `backend/`
   — Render detects the `Dockerfile` (one worker by design, see its comment). Instance
   type: **Free**.
3. Environment variables:
   - `OPENROUTER_API_KEY`
   - `API_SHARED_SECRET` — mint one (`openssl rand -hex 32`); the same value goes to
     Vercel in step 3. Without it the backend refuses every paid request (045/#143)
   - `POSTGRES_USER` (`postgres.<project-ref>`), `POSTGRES_PASSWORD`, `POSTGRES_DB`,
     `POSTGRES_HOST`, `POSTGRES_PORT` — the session-pooler values from step 1
   - `PROFILE` — leave unset for `dev` while dark; `prod` is a deliberate act
   - `FRONTEND_ORIGIN` — the Vercel URL, once step 3 exists (CORS, now a second
     layer rather than load-bearing: the browser talks to the Vercel proxy)
4. The service URL (`https://….onrender.com`) is the API URL. First responses after an
   idle spin-down take ~1 minute — that's the free tier, not a bug.


## 3 — Vercel (the frontend)

1. Import the repo, root directory `frontend/` (Next.js is auto-detected).
2. Two environment variables, both server-side only (nothing `NEXT_PUBLIC_*` — the
   browser talks to this app's own `/api/*` proxy routes, which hold these):
   - `API_URL` = the Render URL (no trailing slash)
   - `API_SHARED_SECRET` = the value from step 2
3. Deploy; then go back to Render and set `FRONTEND_ORIGIN` to the Vercel URL.

## 4 — cron-job.org (the keep-warm)

Create a free account at cron-job.org, add a job hitting `<render-url>/health` **every
12 minutes**, and switch on failure notifications. One ping does triple duty: keeps
Render inside its 15-minute spin-down window, keeps Supabase off its 7-day idle pause,
and exercises a real database round-trip 120 times a day.

## 5 — GitHub (already in the repo)

- CI (`.github/workflows/ci.yml`) runs both suites on every push — nothing to configure.
- The daily check (`.github/workflows/keepalive.yml`) curls `/health` and **fails
  loudly** unless the database answers `"db":"up"` — cron-job.org notifies by email; a
  red workflow run is harder to miss. Activate it by setting the repository
  **secret** `DEPLOY_HEALTH_URL` to the Render URL; until then it skips quietly. A
  secret rather than a variable (#187): run logs are public here, and curl's failure
  messages name the host — secrets are masked in logs, variables are not.

## 6 — Sign in with Google (063/#158)

Until this step is done the deploy behaves exactly as before: `SUPABASE_PROJECT_URL`
unset means the backend counts a forwarded address rather than a person, so the app
still runs — it just cannot enforce a per-account limit. Every action below is a
dashboard action; none of it can be done from the repo.

1. **Google Cloud Console → APIs & Services → Credentials → OAuth client ID (Web).**
   Authorized JavaScript origins: the Vercel URL. Authorized redirect URI: the one
   Supabase shows on its Google provider page. Keep the Client ID and Client Secret.
2. **Supabase → Authentication → Providers → Google:** enable it, paste the Client ID
   and Secret. Leave every other provider off — a disposable inbox is a free unlimited
   account factory, which is why 092 chose Google only.
3. **Supabase → Authentication → JWT signing keys: *Migrate JWT secret*, then
   *Rotate keys*.** Do not skip this. Supabase has not migrated existing projects off
   the legacy shared secret, and until it is done
   `<project>/auth/v1/.well-known/jwks.json` **returns no keys at all** — the backend
   would then refuse every session it was handed. The backend accepts ES256 and RS256
   only; the legacy HS256 secret is deliberately not accepted, because a backend that
   verifies with a shared secret also knows how to mint tokens with it. After rotating,
   wait out one access-token lifetime (default 1 hour) before revoking the legacy key.
4. **Render → Environment:** `SUPABASE_PROJECT_URL` = `https://<ref>.supabase.co`
   (no trailing slash), `SUPABASE_SERVICE_KEY` = the project's secret/service key.
   The service key bypasses row-level security, so it belongs here and nowhere else.
5. **Vercel → Environment Variables**, all three `NEXT_PUBLIC_*` and therefore public
   by design — they identify, they do not authorise:
   - `NEXT_PUBLIC_SUPABASE_URL` = the same project URL
   - `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` = the publishable (`sb_publishable_…`) key,
     or the legacy `anon` key on an older project
   - `NEXT_PUBLIC_GOOGLE_CLIENT_ID` = the Client ID from step 1

   **Set these before the build, not after.** Next inlines `NEXT_PUBLIC_*` at build
   time, so a value added afterwards is not picked up until the next deploy.
6. **Redeploy both**, then confirm the checks below.

The publishable key in step 5 reaches the project's REST API, so the schema is
closed to it: every table in `public` gets row-level security with no policies,
applied by the seed and again at each startup (`persistence.deny_data_api`).
Nothing to do by hand — but if a table is ever created directly in the Supabase
SQL editor, it is exposed until one of those runs.

Two things worth knowing before they surprise someone:

- A free Supabase project pauses after a week of inactivity, and a project restored
  after 2025-11-01 comes back **without** its legacy `anon`/`service_role` keys. If the
  Vercel variable holds an `anon` key, a pause/restore cycle breaks sign-in. The
  cron-job.org ping in step 4 is what keeps the project from idling that far.
- Deleting a user does not invalidate a token already issued to them; it stays valid
  until it expires (default 1 hour). The backend takes that into account and is
  documented at `main.forget_me`.

## Done-when checks (ticket 087's bar)

- `curl <render-url>/health` → `{"status":"ok","db":"up"}`
- the Vercel page runs a dev-profile evaluate end to end, and an analyst turn streams
- cron-job.org shows a run history of green pings 12 minutes apart
- the keep-alive workflow has one green scheduled run
- the bill everywhere reads $0.00 — no card is on file anywhere

Once step 6 is done, four more:

- `curl -X POST <render-url>/evaluate -H 'X-API-Key: …' -d '…'` with **no** bearer
  token → `401`. A run that starts without a signed-in person is the whole bug this
  guards against.
- the same call with a token from a *different* Supabase project → `401`
- signing in on the Vercel page never navigates away — the typed copy survives it
- `GET /api/me` reports `runs_remaining` and it drops by one after a run
