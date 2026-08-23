# Deploy targets — where the backend and frontend run, the 059 result

**Researched 2026-08-23.** Every number below is from an official pricing or docs page
read that day (Supabase facts: read 2026-08-21, from the database half of this ticket).
Ticket: [059 · #154](https://github.com/Subaru-Goto/PanelVerdict/issues/154). Community
threads and third-party comparisons were used only as pointers, never as sources;
anything an official page would not confirm is flagged **UNVERIFIED**.

## Verdict: Vercel Hobby (frontend, $0) + Railway Hobby (backend, $5/mo) — $5.00/mo total

The demo stack lands at **$5.00/month, flat**: Next.js 16 on Vercel's free Hobby plan,
the FastAPI backend as one always-on Railway Hobby service with outbound IPv6 enabled
(direct Supabase connection, no IPv4 add-on), Supabase free tier, and the daily
keep-alive ping on GitHub Actions ($0 on a public repo). Runner-up is Fly.io for the
backend (~$3.35/mo, cheaper but usage-metered and auto-stop-by-default); Cloud Run and
Vercel-for-backend are disqualified by the correctness constraint below, and Render by
IPv4-only networking plus a higher price.

## The constraint that does the sorting

The analyst chat's conversation memory is an **in-process `InMemorySaver`** held for the
process lifetime (`backend/app/main.py`: "One saver for the process lifetime — threads
must outlive requests, which is the whole point of a checkpointer"; `analyst.py`: "a
restart forgets threads and a second worker would not share them"). A paused LangGraph
run must therefore meet its resume request **in the same live process**. That turns
three hosting behaviours from latency nuisances into correctness bugs:

1. **Sleep / scale-to-zero** — the process dies between requests; every thread is lost.
2. **Instance recycling** — "a warm instance" is not "the same instance"; same loss.
3. **Multiple workers/replicas** — the resume can land on a worker that never saw the
   thread. The backend runs **one replica, one uvicorn worker** until the Postgres
   checkpointer (the documented scale-up path, not a redesign) replaces the in-memory one.

So the backend host must run one always-on, never-recycled process. The frontend has no
such constraint — static/ISR pages plus API calls to the backend.

## Postgres: decided — Supabase (2026-08-21)

Recorded here so this doc stands alone; the decision and sources live in the ticket
(all Supabase pages read 2026-08-21):

- **pgvector on the free tier: yes** — HNSW + `vector_cosine_ops`, matching `schema.sql`.
- **Compute is always-on** (never scales to zero); long-lived direct connections are the
  documented pattern — what the checkpointer needs. Nano free tier: 60 direct / 200
  pooled connections.
- **Free projects pause after 7 idle days** — mitigated by an external daily cron ping
  (decided; "a few user requests to the database each day over the previous week is
  enough" to stay active). Pro ($25/mo) removes pausing and is the answer if real
  traffic arrives.
- **Direct connections are IPv6-only** unless the IPv4 add-on ($0.0055/hr ≈ $4/mo) is
  bought. The Supavisor **session** pooler runs on IPv4 on all tiers — the fallback for
  IPv4-only hosts. Transaction mode is unusable: psycopg3 uses prepared statements.

That IPv6 caveat is why **outbound IPv6 is a first-class criterion** below: a host with
IPv6 egress talks to Supabase directly for $0; an IPv4-only host pays $4/mo or takes the
session-pooler detour.

## The field, six criteria each

| | Railway | Render | Fly.io | Cloud Run | Vercel | Koyeb |
|---|---|---|---|---|---|---|
| cheapest always-on | **$5/mo flat** (Hobby, incl. $5 usage) | $7/mo (Starter, 0.5 vCPU/512 MB) | $3.32/mo (shared-1x 512 MB, ams) | $6.57/mo idle floor, CPU-throttled; true always-CPU $44.71/mo | n/a (functions only) | $2.68/mo (eco-micro 512 MB) |
| sleeps? | opt-in only | free: yes (15 min); paid: never | **default: auto-stop** — must disable | instance replaceable anytime | ephemeral by design | free: forced (1 h); paid: no |
| outbound IPv6 | **yes (opt-in toggle)** | **no (IPv4-only)** | **yes** | yes, via VPC machinery | UNVERIFIED | UNVERIFIED |
| cold start | none (unless opted in) | free: ~1 min | none when always-run | possible on replacement | occasional (functions) | free tier only |
| secrets | sealed vars (write-only) | env groups + secret files | encrypted vault, write-only | Secret Manager (~$0) | sensitive env vars | managed secrets |
| native cron | yes (≥5 min, UTC) | yes ($1/mo min) | fuzzy daily/hourly only | 3 jobs free | daily-only on Hobby, ±59 min | none found |

### Railway — the pick for the backend

- **Hobby is $5/month and includes $5 of usage**; unit prices RAM $10/GB/mo
  ($0.000231/GB/min), vCPU $20/mo, egress $0.05/GB (docs.railway.com/pricing/plans, read
  2026-08-23). A ~0.25 GB near-idle FastAPI container derives to ≈ $2.85/mo of usage —
  inside the credit, so the bill is exactly $5. At a steady 0.5 GB it is ≈ $5.35. The
  Free plan ($1/mo credit) cannot sustain always-on: workloads stop at zero credit.
- **Nothing sleeps unless you opt in**: scale-to-zero is the "Serverless" toggle, off by
  default ("Enabling Serverless on a service tells Railway to stop a service when it is
  inactive" — docs.railway.com/deployments/serverless, read 2026-08-23). No official
  sentence says "always-on by default" verbatim — flagged UNVERIFIED as phrasing — but
  every page frames sleeping as opt-in and none describes forced sleep on any plan.
- **Outbound IPv6: supported, opt-in, off by default** — "Railway supports outbound IPv6
  connections on an opt-in basis per service … Outbound IPv6 is disabled by default";
  while disabled, IPv6 attempts fail with ENETUNREACH
  (docs.railway.com/networking/outbound-networking, read 2026-08-23). Enable via
  Settings → Networking → "Enable Outbound IPv6" (redeploy applies it). Railway's own
  help board has Supabase-ENETUNREACH threads with exactly this fix. **Deploy checklist
  item #1.**
- **Secrets**: sealed variables are write-only — "provided to builds and deployments but
  never visible in the UI nor … via the API" (docs.railway.com/variables, read
  2026-08-23). The OpenRouter key goes in sealed.
- **Cron**: native, crontab syntax, ≥5-minute granularity, UTC
  (docs.railway.com/cron-jobs, read 2026-08-23) — a fallback for the keep-alive ping if
  GitHub Actions ever misbehaves.
- Next.js + FastAPI as two services in one project is the documented pattern; both
  together ≈ $5–11/mo (frontend idle RAM is an estimate, UNVERIFIED) — the consolidation
  path if Vercel's terms ever bite.

### Fly.io — runner-up

- Free tier is gone for new orgs (plans deprecated 2024-10-07; trial = 2 machine-hours
  or 7 days — fly.io/docs/about/free-trial, read 2026-08-23). shared-cpu-1x: 256 MB
  $2.02/mo, 512 MB $3.32/mo (Amsterdam; per-second, region-varies —
  fly.io/docs/about/pricing, read 2026-08-23). The folk-remembered "invoices under $5
  waived" policy appears on **no official page** post-2024 — UNVERIFIED, budget as gone.
- **Outbound IPv6 verified**: "Machines often egress over IPv6 when the destination has
  a AAAA record and the application prefers it" (fly.io/docs/networking/egress-ips, read
  2026-08-23); the platform's private networking is IPv6-native (6PN).
- **The trap**: `fly launch` generates `auto_stop_machines = "stop"`,
  `min_machines_running = 0` — the checkpointer-breaking config is the *default*
  (fly.io/docs/launch/autostop-autostart, read 2026-08-23). Always-run requires
  `auto_stop_machines = "off"`, and it must survive every future fly.toml regeneration.
- Egress $0.02/GB with **no free allowance** for new orgs; secrets are a write-only
  encrypted vault; cron is fuzzy `hourly/daily/weekly/monthly` only — no cron
  expressions (fly.io/docs/machines/flyctl/fly-machine-run, read 2026-08-23).
- Backend-only: ~$3.35/mo. Cheaper than Railway but uncapped, and two defaults
  (auto-stop, region pricing) need active tending.

### Render — survives the constraint, fails the IPv6 criterion

- Free web services "spin down … 15 minutes without receiving any inbound traffic" and
  take "about one minute" to wake (render.com/docs/free, read 2026-08-23) — free tier
  breaks the checkpointer *and* is user-visibly slow. "Paid instance types do not spin
  down": Starter, 0.5 vCPU/512 MB, **$7/mo** (figure from Render's own comparison
  article, read 2026-08-23 — the pricing page is client-rendered; re-check before
  committing).
- **IPv4-only**: "Render uses IPv4" (render.com/docs/configure-other-dns, read
  2026-08-23); the outbound-IP docs never mention IPv6; the IPv6 feature request has
  been open since 2021-01-29 with no official response, with commenters citing Supabase
  specifically. The Supabase-direct failure itself is UNVERIFIED (Render's forum archive
  is offline), but the official IPv4-only statements make the conclusion safe: Render
  means session pooler or the $4/mo IPv4 add-on.
- Frontend as a free static site works, but the Hobby workspace now includes only
  **5 GB/mo bandwidth** ($0.15/GB after — changelog 2026-04-23, read 2026-08-23). Cron
  exists but has a $1/mo minimum per job.

### Google Cloud Run — disqualified by instance identity, not price

- min-instances=1 keeps *a* warm instance, never *the same* one: "Minimum instances can
  be restarted at any time"; infrastructure rebalancing can replace them
  (docs.cloud.google.com/run/docs/configuring/min-instances, read 2026-08-23). With an
  in-memory checkpointer that is thread loss on Google's schedule — **fails the
  constraint at any price**.
- The prices anyway: request-based + min-instances idle floor ≈ **$6.57/mo** at
  0.5 vCPU/512 MiB — but CPU is throttled between requests, so a background Python
  continuation is not guaranteed to run. True always-allocated CPU requires ≥1 vCPU
  (sub-1-vCPU forces request-based billing): **$49.93/mo list, $44.71 after free tier**
  (cloud.google.com/run/pricing, us-central1, read 2026-08-23).
- Outbound IPv6 exists (GA 2025-11-06) but only via Direct VPC egress on a dual-stack
  subnet in a custom-mode VPC plus an IAM role; NAT64 unsupported; dual-stack adds
  cold-start latency. Whether *default* egress is IPv4-only is never stated verbatim —
  UNVERIFIED as a quote, implied by the feature's existence.

### Vercel — frontend yes ($0), backend no by design

- Hobby is free and fits the demo: 100 GB Fast Data Transfer, 1M function invocations,
  1M edge requests, 5K image transformations/mo; overages **pause features rather than
  bill** (vercel.com/docs/plans/hobby and /docs/limits, read 2026-08-23). Constraint:
  Hobby is "restricted to non-commercial personal use only" — a portfolio demo
  qualifies; anything monetized means Pro ($20/seat).
- The backend does not fit — not because of Python (FastAPI is a named preset of the
  Python runtime) but because everything runs as functions: 300 s max duration on Hobby,
  "spins up a computing instance when a request arrives and spins it down when the
  request completes", and Fluid compute's instance reuse is an optimization, never a
  routing guarantee ("Functions **can** reuse resources"; "Cold starts can still
  happen"). Vercel's own KB on always-listening processes: they "will not work on
  Vercel" — it recommends Cloud Run/Fly/Render instead (vercel.com/kb, read 2026-08-23).
- Outbound IPv6: UNVERIFIED (docs say "we do not support IPv6 yet" about inbound;
  outbound is undocumented) — irrelevant in the chosen shape, since the frontend talks
  HTTPS to the backend, never to Postgres.
- Cron on Hobby: daily-only, ±59 min precision — usable as a second keep-alive if ever
  needed, though GitHub Actions stays the default.

### Also checked: Koyeb, Hetzner

- **Koyeb** (found while scanning for better options): eco-micro, 0.25 vCPU/512 MB,
  **$2.68/mo** always-on, pay-as-you-go, managed secrets
  (koyeb.com/docs/reference/instances, read 2026-08-23). The free tier force-sleeps
  after 1 h (unusable here). Strikes: outbound IPv6 UNVERIFIED, no native cron, and two
  official pages disagree on included bandwidth (100 GB vs 1 TB). Cheapest credible
  backend host if its IPv6 story ever gets documented.
- **Hetzner Cloud**: after the 2026-06-15 price rise, entry CX23 is €5.49/mo (2 vCPU /
  4 GB / 20 TB traffic, EU locations only; US starts ~$20.49), IPv6 free, IPv4 skippable
  for −€0.50 (docs.hetzner.com price-adjustment and ipv4-pricing pages, read
  2026-08-23). Enormous capacity per euro, but raw VPS: TLS, deploys, secrets, patching
  all self-managed — the wrong trade at demo scale.

## The recommended shape, priced

| piece | platform | $/mo |
|---|---|---|
| frontend (Next.js 16) | Vercel Hobby | 0.00 |
| backend (FastAPI, always-on, 1 worker) | Railway Hobby (≈$2.85 usage inside the $5 credit) | 5.00 |
| Postgres + auth + pgvector | Supabase free tier | 0.00 |
| daily keep-alive ping | GitHub Actions cron (public repo) | 0.00 |
| Supabase IPv4 add-on | not needed — Railway outbound IPv6 | 0.00 |
| **total** | | **5.00** |

Worst case ≈ $5.35/mo if the backend idles at a steady 0.5 GB. **Runner-up:** swap
Railway for Fly.io shared-cpu-1x 512 MB → ~$3.35/mo, accepting usage-metered billing,
the auto-stop default to disarm, and fuzzy-only native cron.

Deploy checklist bred by this research: (1) enable Railway's "Enable Outbound IPv6"
toggle before first connecting to Supabase — the failure mode is ENETUNREACH, not a
clear error; (2) uvicorn with one worker, one replica — the InMemorySaver demands it;
(3) OpenRouter key as a Railway **sealed** variable; (4) fallback path if IPv6 ever
misbehaves: Supavisor session pooler (IPv4, free) — never transaction mode.

## UNVERIFIED ledger

- Railway: no official sentence states "always-on by default" verbatim (opt-in framing
  is consistent everywhere); "private networking is free" not captured as a quote;
  IPv6-feature launch date unknown; frontend idle-RAM estimate is mine.
- Render: $7 Starter price sourced from an official article, not the (client-rendered)
  pricing table; the Supabase-direct failure report itself (forum archive offline).
- Fly.io: the under-$5 invoice waiver — on no official page; treated as discontinued.
- Cloud Run: "default egress is IPv4-only" never stated verbatim.
- Vercel: outbound IPv6 undocumented.
- Koyeb: outbound IPv6 undocumented; bandwidth allowance self-contradictory across two
  official pages.
