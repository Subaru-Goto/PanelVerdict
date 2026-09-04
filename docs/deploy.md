# Deploying PanelVerdict — the $0/month shape

The platform decision and every sourced number live in
[research/deploy-targets.md](research/deploy-targets.md) (see its 2026-08-23 amendment:
the budget is zero); ticket
[087/#180](https://github.com/Subaru-Goto/PanelVerdict/issues/180) carries the build.
This is the operator's checklist — what to click, in what order, and why the order
matters. **Ship dark**: the URL stays unannounced until auth (#158) and the
cost-ceiling implementation hold — the edge secret and rate limits landed with #143.
**Both conditions are met as of 2026-08-25** (#158 merged in PR #204, the cap in #192), so
announcing is now a decision rather than a blocker.
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
daily cap) is the second, with the same symptom. `corpus_chunks` (018/#124, the
analyst's explanation corpus) is the third — without it every "what does this mean"
question ends the turn, which is the flagship interaction.

The corpus is also the one case with a cheap remedy: `uv run python -m app.seed
--corpus-only` creates the table and reseeds it for a handful of embeddings, instead
of re-running `--size full` and paying for a plausibility-QC pass nobody needs.
Re-running the same seed command creates all three.

Cheaper still, and the right tool when nothing needs *seeding*: `uv run python -m
app.seed --schema-only` applies `schema.sql` and the row-level-security sweep and
stops there — no personas, no corpus, no embeddings, and no API key. That is the
command to run on a deploy that adds a table or a column. `tests.kept` (035/#136)
is the first column case: without it no finished run is stored, and every new
test's analyst answers 404 while the run itself returns 200.

**Adding a column to a table that already exists** goes at the bottom of
`backend/app/schema.sql`, in the documented `ALTER TABLE … ADD COLUMN IF NOT EXISTS`
form — never by editing the `CREATE TABLE` above it, which `IF NOT EXISTS` will not
re-apply. The form is enforced, not suggested: `app.persistence` refuses a bare `ADD
COLUMN`, because the file runs on every seed and every `--schema-only` apply, and
a statement that fails mid-file takes the row-level-security sweep after it down
too. Additive only — no
`DROP COLUMN`, no rename, no type change: during a rollout an older instance is still
serving, and `votes` is paid model output that cannot be regenerated. Applying is
manual until launch; automating it is 083/#173's deferred half.

**You do not have to remember any of this.** On every merge to `main`, CI's
`schema-drift` job runs `--check-schema` against the project and fails red if the
deployed database is missing anything this build writes. It reads and never applies.

Give it a role of its own — **not** the pooler owner the seed step uses. That owner
can read every table and drop any of them, including `votes`, which is paid model
output. Anything holding the CI secret can use it, so the secret should not be able
to do more than look:

```sql
-- In Supabase: SQL Editor. Pick your own password.
CREATE ROLE drift_check LOGIN PASSWORD '…';
GRANT USAGE ON SCHEMA public TO drift_check;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO drift_check;
-- Tables created by future schema applies inherit SELECT automatically —
-- without this, every new table is invisible to the role and the check
-- reports it "missing every column" on a current database (measured
-- 2026-09-02: three tables created after the GRANT did exactly that).
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO drift_check;
-- The sweep above also catches the checkpointer's tables, which hold
-- customer analyst transcripts. The drift check never reads them, so the
-- CI secret must not be able to: revoke, and re-revoke if a checkpointer
-- migration ever adds a table (default privileges will have re-granted it).
REVOKE SELECT ON checkpoints, checkpoint_blobs, checkpoint_writes,
  checkpoint_migrations FROM drift_check;
```

The default-privileges line is a deliberate trade: a future table holding
something sensitive is readable by `drift_check` the moment it exists, until a
`REVOKE` like the one above says otherwise. That beats the alternative — a
check that silently goes blind on every table added after the GRANT — but it
means a new sensitive table owes this file a revoke line.

`SELECT` and not merely `CONNECT`, which looks like the tighter answer and is not:
`information_schema.columns` shows a role only the columns it may read, so a
connect-only role sees nothing and the check reports *every* table as missing on a
current database. Measured — `test_the_drift_check_needs_select_and_not_only_connect`
pins both halves. The `ALTER DEFAULT PRIVILEGES` line is what covers tables
added later — a bare `GRANT` covers existing tables only, and a table the role
cannot see is reported missing, not denied.

Then set the repository secrets — Settings → Secrets and variables → Actions →
Secrets: `DEPLOY_POSTGRES_HOST`, `DEPLOY_POSTGRES_USER`, `DEPLOY_POSTGRES_PASSWORD`,
and optionally `DEPLOY_POSTGRES_PORT` (defaults to `5432`) and `DEPLOY_POSTGRES_DB`
(defaults to `postgres`). Host and port are the **session pooler**'s, as in step 2.
Copy the username from Connect → Session pooler rather than composing it: the pooler
qualifies the role with the project ref, the way `postgres.<project-ref>` is
qualified there.

Until the secrets exist the job posts a warning on the run and passes, so this
workflow lands with the code and the deploy lands later — a green tick alone does not
mean the schema was checked, which is why the warning is there. Secrets rather than
variables because this repo is public: run logs are public, and a connection error
names the host exactly when the check goes red.

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
   - `MISTRAL_API_KEY` — the chat pre-flight's classifier (120/#279). With
     `SCREENER_REQUIRED=true` the boot refuses without it, exactly as it does
     without a screening model; the key is free at Mistral's listed price and
     used by nothing else
   - `API_SHARED_SECRET` — mint one (`openssl rand -hex 32`); the same value goes to
     Vercel in step 3. Without it the backend refuses every paid request (045/#143)
   - `POSTGRES_USER` (`postgres.<project-ref>`), `POSTGRES_PASSWORD`, `POSTGRES_DB`,
     `POSTGRES_HOST`, `POSTGRES_PORT` — the session-pooler values from step 1
   - `PROFILE` — leave unset for `dev` while dark; `prod` is a deliberate act
   - `SCREENER_REQUIRED=true` — the screener is the only control on the
     untrusted-input path, and this is the deployment it protects: a screening
     model the startup probe finds unavailable fails the boot here instead of
     serving without the control (072/#163). Priced and scoped honestly: the
     probes are one paid screening call and one free moderation call per boot
     and can hold a cold start for up to `SCREEN_TIMEOUT_SECONDS` (10s) plus
     `GUARD_TIMEOUT_SECONDS` (2s) inside the ~30s wake the keep-warm
     ping already budgets for; and it asserts the control at the boot instant
     only — a key or model revoked mid-life still fails open per request,
     one ERROR log line each, until the next boot
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
4. Check **Settings → Functions** shows Fluid compute on (the default for new
   projects). The proxy routes' 300 s budget in `frontend/vercel.json` is the Hobby
   maximum Vercel's duration table gives *with* Fluid compute (docs read 2026-09-04).
   Before Fluid compute the plan's ceiling was 60 s (Vercel changelog, "Vercel
   Functions for Hobby can now run up to 60 seconds"), so an older project should
   confirm the setting before relying on the budget.

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
- `GET /api/me` reports `runs_remaining` and it drops by one after a run; it also
  reports `saved_tests` against `saved_tests_cap`, and `saved_tests` drops by one
  after a delete in the rail (the form's full-rail notice reads these two)
