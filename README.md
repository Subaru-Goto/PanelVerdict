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
[`docs/research/task-framing.md`](docs/research/task-framing.md). Every number the
app shows carries its own uncertainty for exactly this reason.

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
`NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local`.

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

## What a run costs

Real money, every time — there is no free tier or mock mode in the app itself.
One vote is roughly **$0.0007**, and the panel size comes from `PROFILE` in
`.env`:

| profile | panel | ~cost per run |
|---------|-------|---------------|
| `dev` (default) | 25 | $0.018 |
| `demo` | 100 | $0.073 |
| `prod` | 200 | $0.145 |

`PROFILE` is not in `.example.env` — it defaults to `dev`, and the default is
the cheapest on purpose: forgetting to choose should cost a cent, not a tenth of
your credit. Add `PROFILE=demo` or `PROFILE=prod` to `.env` to change it.

Repeat runs of the same headlines against the same panel reuse the cached votes,
so they cost only the one targeting call.

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
| `db/` | database init |
| `docs/` | how the thing works and why |
| `docs/research/` | the sourced numbers — every constant with a citation traces here |
| `issues/` | the plan, and the decision log |

## Where the reasoning lives

Two conventions worth knowing before you change anything:

**Numbers need a source.** A constant is either derived in front of you, cited to
something in `docs/research/`, or explicitly signed off. If you find one that
isn't, that's a bug.

**Comments explain *why*, never *what*.** The code says what it does. A comment
is there for the thing you'd otherwise have to rediscover — a rejected
alternative, a measured surprise, a constraint that isn't local. Ticket numbers
don't belong in them; `issues/` is where that history lives.
