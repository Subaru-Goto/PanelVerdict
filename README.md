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
     two headlines  +  controls  +  optional audience text
                              │        (acted out, not translated)
                              ▼
   pool  ──▶  panel preview  ──▶  [ YOU APPROVE ]  ──▶  votes  ──▶  verdict  ──▶  kept
  (SQL)      (who gets seated)     nothing is bought     (one model   (Beta      (to your
                                     until here           call each)   posterior)  account)
```

1. **Ask.** Two headlines, plus explicit controls for who should judge them —
   country, age span, gender, education, income. Picking nothing means anyone.
   Leave it all alone and the panel is a cross-section of the pool, with no model
   called.
2. **Role-play, if you asked for it.** The optional "who else are they?" field is
   *not* translated into a query: nothing in the pool records who shops for
   groceries online, so one model call turns your sentence into an instruction
   every panelist is asked to act out, and the report says which part of the
   audience was matched from survey data and which part was acted
   ([094](https://github.com/Subaru-Goto/PanelVerdict/issues/200)). Copy that tries to
   redirect the panel rather than be judged by it is refused before anything is
   bought.
3. **Retrieve.** Every control *filters*, then a seeded uniform sample picks the
   panel. Filtering rather than ranking is what makes it an audience rather than a
   handful of extremes.
4. **Approve the panel.** The run stops and shows you who would be seated, and how
   your audience was read. **No votes are bought until you accept**
   ([076](https://github.com/Subaru-Goto/PanelVerdict/issues/166)) — so a reading
   you did not mean costs you nothing, and adjusting it does not spend a run.
5. **Vote.** Each panelist reads both headlines and picks one, with a reason.
   Votes fan out concurrently and are cached on the exact question asked, so
   re-running the same headlines against the same panel buys no votes.
   Presentation order is split exactly 50/50, because the model favours whatever
   it sees first about two-thirds of the time.
6. **Decide.** A Beta posterior over the panel's preference gives a share, a
   credible interval, and the probability the lead is big enough to act on. It can
   stop early when the answer is already clear.
7. **Explain.** An analyst agent reads the run through tools — including a cited
   corpus — and answers questions about it in plain language.
8. **Keep it.** The finished report is stored against your account, so a refresh
   or a crashed render no longer loses what you paid for. Past tests are listed,
   searchable, reopenable and deletable, and deleting the account deletes them
   ([117](https://github.com/Subaru-Goto/PanelVerdict/issues/252)).

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

**Deploying it.** The app runs on Vercel + Render + Supabase within their free
tiers, kept warm by a scheduled ping.
[`docs/deploy.md`](docs/deploy.md) is the operator's checklist, and
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
and since the controls replaced translation
([094](https://github.com/Subaru-Goto/PanelVerdict/issues/200)) there is no targeting
call left to pay for — so a re-run costs **nothing** unless you changed the
audience sentence, which buys one rewrite (~$0.0012). Visiting the panel gate is
free, and adjusting the reading there does not spend a run.

The cache serves a matching answer **forever**, deliberately: the same target and
the same headlines must never be re-paid for
([040](https://github.com/Subaru-Goto/PanelVerdict/issues/138), where the earlier
"only today's votes" requirement was reversed). Retention is therefore
user-managed — a stored report lasts until its owner or their account deletes it.

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
- **What is unsettled, and what would settle it.** That run's personas were not
  matched to the 2013–15 readership the control was drawn from, so failing it does
  not cleanly separate *"the panel does not reproduce copy effects"* from *"these
  personas are not that audience."* A demographically-matched replication is what
  would answer it, in either direction.

**2. The explanation corpus is small, and evaluated on questions we wrote
ourselves.** The analyst does not answer "what does a credible interval mean"
from its own weights: it retrieves from committed documents and shows the source.
What is honest to say about it:

- It is **two documents, fifteen passages** — what the verdict means and who the
  panel is. Anything outside that returns nothing and the analyst says so, which is
  the intended behaviour rather than a gap being hidden.
- It was checked on **fourteen question–section pairs written by the corpus's own
  author**, which is the failure mode this project has been bitten by before: a
  probe set built from the same imagination as the thing under test cannot find what
  that imagination missed. Numbers and limits:
  [`docs/research/corpus-retrieval-check.md`](docs/research/corpus-retrieval-check.md).
- **No figure appears in any document**, so a retrieved passage cannot contradict
  the numbers on the report beside it.
- The persona search that exists alongside it is weak on its own terms — it returns
  five panelists out of up to 200 and is blind to which variant they chose, so it
  characterises individuals rather than the panel
  ([041](https://github.com/Subaru-Goto/PanelVerdict/issues/139),
  [043](https://github.com/Subaru-Goto/PanelVerdict/issues/141)).

**3. Every run spends real money, so the app refuses before it buys.** Signing in
is required to run a test: runs are counted against a verified account, analyst
turns are capped, and a ledger refuses over a limit before anything is bought.
Above those sits a global daily ceiling, and a hard spend cap on the model key
behind it. What the ceilings are and why they were chosen that way lives in
[`064`](docs/decisions/064-the-cost-ceilings.md) and
[`docs/least-privilege.md`](docs/least-privilege.md) — not here, since the
figures change and a README is the wrong place to read them from.

One honest caveat about the ceiling: the price of a *run* is a measurement, and
the price of an analyst *turn* is a stand-in, because nobody has measured a turn
yet. The cap therefore holds against the shape of the spend more reliably than
against its exact size.

## Tests

No test calls a paid model — every model is a double, and the database ones run
against a throwaway container, so the whole suite is free.

```bash
cd backend  && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
cd frontend && npm test && npm run typecheck && npx eslint app __tests__
```

`npm run typecheck`, not a bare `npx tsc --noEmit`: `tsconfig.json` includes
`next-env.d.ts`, which is generated and gitignored, so without `next typegen`
first you type-check a *different program* than CI does — measured, on a fresh
checkout an image import is `TS2307`
([114](https://github.com/Subaru-Goto/PanelVerdict/issues/245)). CI also runs
this before the tests, because `next build` type-checks only what it compiles
into the app — a type error in `__tests__` used to ship green, and that is where
the frontend's mirror of the response contract is checked.

## Layout

| path | what lives there |
|------|------------------|
| `backend/app/` | the pipeline: `targeting` → `persistence` → `vote` → `verdict`, assembled by `pipeline`, served by `main` |
| `backend/app/analyst.py` | the "Ask the analyst" agent and its tools |
| `backend/app/schema.sql` | every table, and the one place additive `ALTER TABLE … ADD COLUMN IF NOT EXISTS` may go — the form is enforced, not suggested ([115](https://github.com/Subaru-Goto/PanelVerdict/issues/248)) |
| `backend/app/seed.py` | pool generation — the only paid CLI, plus two free entry points: `--schema-only` applies the schema and stops, `--check-schema` reports drift and never applies |
| `frontend/app/` | Next.js report UI, the analyst dock, and the rail of past tests |
| `frontend/app/api/` | server-side proxy routes — the only place the backend URL and edge secret exist |
| `db/` | database init |
| `docs/design/prototype.html` | the whole interface as a click-through, and a decision record: several decisions exist only in its comments |
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
