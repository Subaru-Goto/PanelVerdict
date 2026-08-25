# PanelVerdict

**A/B test a headline against a synthetic panel.** Describe an audience in plain
language, give it two headlines, and a panel of AI personas votes between them —
you get a verdict with its uncertainty, the reasons behind it, and an analyst you
can ask follow-up questions.

It answers *"which of these will probably land better, and how sure can I be?"*
before you publish, instead of after weeks of live traffic.

**Read the caveat before you trust a number.** The panel is synthetic. It is
useful where two headlines say genuinely different things, and it is *unvalidated*
where they say the same thing differently — a measured limitation, written up in
[`docs/research/task-framing.md`](docs/research/task-framing.md) and summarised
under [Known limitations](#known-limitations). Every number the app shows carries
its own uncertainty for exactly this reason.

---

## How a run works

```
target description ──▶ translator ──▶ structured query ──▶ pool ──▶ panel
      (a model call)                     (plain SQL)          (personas)
                                                                  │
                          verdict ◀── Bayesian layer ◀── votes ◀──┘
                       (probabilities)                  (one model call each)
```

1. **Translate.** A model turns "young Japanese homeowners" into a query the pool
   can serve — country, age span, income, education, personality. Anything it
   cannot express is reported rather than silently dropped. Leave the target
   blank and the panel is a cross-section of the whole pool; no model is called.
2. **Retrieve.** Every requested attribute *filters*, then a seeded uniform sample
   picks the panel. Filtering rather than ranking is what makes it an audience
   rather than a handful of extremes.
3. **Vote.** Each panelist reads both headlines and picks one, with a reason.
   Votes fan out concurrently and are cached on the exact question asked, so
   re-running the same headlines against the same panel buys no votes — only
   the targeting call, which is not cached. Presentation order is split exactly
   50/50, because the model favours whatever it sees first about two-thirds of
   the time.
4. **Decide.** A Beta posterior over the panel's preference gives a share, a
   credible interval, and the probability the lead is big enough to act on. It
   can stop early when the answer is already clear.
5. **Explain.** An analyst agent reads the run through tools and answers
   questions about it in plain language.

## Getting started

**You need:** Docker, Python with [uv](https://docs.astral.sh/uv/), Node, and an
[OpenRouter](https://openrouter.ai) API key.

**1. Configure.** Copy `.example.env` to `.env` in the repo root and fill it in —
`POSTGRES_*`, `FRONTEND_ORIGIN`, and `OPENROUTER_API_KEY`. The frontend needs
`API_URL=http://localhost:8000` in `frontend/.env.local`.

The browser never calls the backend directly: it talks to the frontend's own
`/api/*` routes, which hold the backend URL and the edge secret server-side.
Nothing here is `NEXT_PUBLIC_*`, because that would ship it to every visitor.
Locally you can leave `API_SHARED_SECRET` unset — the guard is then off, which
is what you want for development.

**2. Start the database.** pgvector-flavoured Postgres:

```bash
docker compose up -d
```

**3. Seed the persona pool.** This costs money — the personas are generated —
so start with `--dry-run`, which prints what a run would cost and calls nothing:

```bash
cd backend
uv run python -m app.seed --dry-run          # free: what would this cost?
uv run python -m app.seed --size dev         # 200 personas, split across countries
```

`--size full` builds 5,000 instead. Both are totals, divided evenly over the
seeded countries (US, JP, DE) — so `dev` is about 67 people per country, enough
to develop against but not to draw a narrow audience from.

Seeding **resumes**: re-running only pays for what is missing.

**4. Run it.**

```bash
cd backend  && uv run fastapi dev app/main.py   # http://localhost:8000
cd frontend && npm install && npm run dev       # http://localhost:3000
```

**Deployed, dark.** The app runs on Vercel + Render + Supabase at $0/month, kept
warm by a cron ping, and is deliberately unannounced until the safety spine is
finished. [`docs/deploy.md`](docs/deploy.md) is the operator's checklist —
`bash scripts/deploy-wizard.sh` walks it step by step.

## What a run costs

Real money, every time — there is no free tier or mock mode in the app itself.
A vote costs **~$0.00015–0.00017** measured, and the panel size comes from
`PROFILE` in `.env`:

| profile | panel | ~cost per run (measured) |
|---------|-------|--------------------------|
| `dev` (default) | 25 | $0.004 |
| `demo` | 100 | $0.016 |
| `prod` | 200 | $0.032 |

These are **measurements**, reconciled against OpenRouter's own USD activity
view during the model gate run
([071](https://github.com/Subaru-Goto/PanelVerdict/issues/162),
[`manipulation-check-luna.md`](docs/research/manipulation-check-luna.md)).
`USD_PER_VOTE` in `backend/app/config.py` rounds up to `0.0002` — that margin
is what the warn-and-proceed budget notice gates on, deliberately a little
pessimistic. The `gpt-5-mini` figures these replaced were $0.018 / $0.073 /
$0.145 per run, so Luna is roughly 70% cheaper.

`PROFILE` is not in `.example.env` — it defaults to `dev`, and the default is
the cheapest on purpose: forgetting to choose should cost a cent, not a tenth of
your credit. Add `PROFILE=demo` or `PROFILE=prod` to `.env` to change it.

Repeat runs of the same headlines against the same panel reuse the cached votes,
so they cost only the one targeting call.

## Known limitations

Three things worth knowing before using the app or judging it. The first is the one that
changes what a number means.

**1. The panel is unvalidated on same-meaning copy — measured, not suspected.**
This is the most significant limitation in the project, and the numbers are in
[`docs/research/task-framing.md`](docs/research/task-framing.md):

- Changing one sentence of the *question* ("which do you prefer?" → "which would
  you click?") flips **38–43% of matched votes**, against a noise floor of 0.19–0.24.
  The verdict-level reading is stabler — the `openness` gradient is identical under
  all three framings — but the vote-level number is framing-dependent.
- **The panel fails its published negative control.** Against 24,333 real Upworthy
  A/B pairs: the lever known to do *nothing* to real clicks produced the largest,
  most consistent preference in the run, and the three levers that *do* move real
  clicks landed at chance.
- So a preference share on two headlines that mean the same thing **is not a
  prediction about readers.** It is informative where the headlines say genuinely
  different things. `preference` remains the shipped framing because nothing in the
  run gives grounds to change it, not because it won.

**2. There is no document-based retrieval corpus.** Retrieval today is
`nearest_panelists` — a pgvector similarity search over persona summaries inside the
analyst's tool set. No prose is chunked, embedded, or retrieved, so when the analyst
explains what a credible interval means it answers from its own weights rather than
from a cited source. Two consequences worth knowing:

- The corpus that would fix it is specified and open:
  [018](https://github.com/Subaru-Goto/PanelVerdict/issues/124).
- The persona search that exists is weak on its own terms — it returns five
  panelists out of up to 200 and is blind to which variant they chose, so it
  characterises individuals rather than the panel
  ([041](https://github.com/Subaru-Goto/PanelVerdict/issues/139),
  [043](https://github.com/Subaru-Goto/PanelVerdict/issues/141)).

**3. The spend guard counts verified accounts.** (Corrected 2026-08-25 — this read "there is no per-user identity, so the spend guard counts addresses" until [063/#158](https://github.com/Subaru-Goto/PanelVerdict/issues/158) shipped Google sign-in: runs are now counted against a verified subject id, three a day.) The
paid endpoints are no longer open — a shared secret admits only calls made
through the frontend's server-side proxy, and a Postgres-backed ledger caps runs
per caller and analyst turns per thread and per caller, refusing before anything
is bought ([045](https://github.com/Subaru-Goto/PanelVerdict/issues/143)). But
with no accounts yet, "caller" means the network address the platform reports:
people behind one NAT share a budget, and somebody with many addresses gets
many. What bounds the determined abuser is a global daily pool — every paid
request is priced at the gate and refused once the day's budget ($1.00) is
spent, whoever asks ([064](docs/decisions/064-the-cost-ceilings.md),
[089](https://github.com/Subaru-Goto/PanelVerdict/issues/192)); a hard spend cap
on the OpenRouter key remains the backstop, and real per-user auth is still to
land ([063](https://github.com/Subaru-Goto/PanelVerdict/issues/158)).

## Next steps

Roughly in the order they would be done, each already specified:

| next | what it changes |
|---|---|
| [018](https://github.com/Subaru-Goto/PanelVerdict/issues/124) | a chunked, embedded, cited corpus, so what a trait level or a credible interval means here comes from a source rather than the model's weights |
| [063](https://github.com/Subaru-Goto/PanelVerdict/issues/158) | real per-user identity, which is what turns the spend guard from per-address into per-person |
| [041](https://github.com/Subaru-Goto/PanelVerdict/issues/139) | which kind of person preferred which variant — the question customers ask next |
| [044](https://github.com/Subaru-Goto/PanelVerdict/issues/142) | a suggestion for the winning headline, framed as a hypothesis the app can then test |
| [047](https://github.com/Subaru-Goto/PanelVerdict/issues/145) | structured logs with a correlation id, so a slow or costly run can be traced |

**And the one that would change what the app may claim:** a
demographically-matched replication of the framing study. Limitation 1 rests on a
run whose personas were not matched to Upworthy's 2013–15 readership, so failing
the negative control there does not cleanly separate *"the panel does not
reproduce copy effects"* from *"these personas are not that audience."*
[`task-framing.md`](docs/research/task-framing.md) is explicit that this is
unsettled — a matched replication is what would settle it, in either direction.

## Tests

No test calls a paid model — every model is a double, and the database ones run
against a throwaway container, so the whole suite is free.

```bash
cd backend  && uv run pytest && uv run ruff check . && uv run ruff format --check .
cd frontend && npm test && npx tsc --noEmit && npx eslint app __tests__
```

## Layout

| path | what lives there |
|------|------------------|
| `backend/app/` | the pipeline: `targeting` → `persistence` → `vote` → `verdict`, assembled by `pipeline`, served by `main` |
| `backend/app/analyst.py` | the "Ask the analyst" agent and its tools |
| `backend/app/seed.py` | pool generation (the only paid CLI) |
| `frontend/app/` | Next.js report UI and the analyst dock |
| `frontend/app/api/` | server-side proxy routes — the only place the backend URL and edge secret exist |
| `db/` | database init |
| `docs/` | how the thing works and why |
| `docs/research/` | the sourced numbers — every constant with a citation traces here |
| `docs/decisions/` | the decision log — closed tickets from the file-tracker era, plus the id→issue mapping |

The plan itself lives on [GitHub Issues](https://github.com/Subaru-Goto/PanelVerdict/issues)
(since 2026-08-21): the issue labelled `wayfinder:map` is the map, its sub-issues are the
tickets.

## Where the reasoning lives

Two conventions worth knowing before you change anything:

**Numbers need a source.** A constant is either derived in front of you, cited to
something in `docs/research/`, or explicitly signed off. If you find one that
isn't, that's a bug.

**Comments explain *why*, never *what*.** The code says what it does. A comment
is there for the thing you'd otherwise have to rediscover — a rejected
alternative, a measured surprise, a constraint that isn't local. Ticket numbers
don't belong in them; `docs/decisions/` and the issue tracker are where that history
lives.
