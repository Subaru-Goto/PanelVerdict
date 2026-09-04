# Two ceilings, chosen: the connection budget and the threads that front it

Ticket 112/#242. Record dated 2026-09-04. Everything measured here was measured on
that date or is quoted from a dated source; the earlier mechanism measurements it
builds on are in `async-cancellation-and-connections.md` (2026-08-30/31).

## The question

How many database connections and how many worker threads may this deployment use
at once, and what happens when it runs out? The async conversion (111/#240) left
both as defaults nobody chose: one connection per request with no connect deadline,
and Python's default executor, `min(32, cpu + 4)`, shared by every `asyncio.to_thread`,
every LangGraph sync node, and every new connection's DNS lookup.

## The numbers

| fact | value | source |
|---|---|---|
| session pooler **Pool Size** granted to this project | **15** | Supabase dashboard, Database Settings → Connection pooling, read 2026-09-04 |
| Nano (Free) database max connections / pooler max clients | 60 / 200 | Supabase compute docs, read 2026-09-04 |
| pooler behaviour at a full pool, session mode | queues the client for up to a minute | Supavisor FAQ, read 2026-09-04 |
| default executor on a 1-vCPU container | 5 workers | derived, `min(32, 1 + 4)`; the sibling record measured 14 on a 10-core dev machine (2026-08-30). Not read off the deployed container: Python 3.13 sizes by `process_cpu_count`, which reads affinity, not the cgroup quota, so a shared host may report its own cores |
| connections the checkpointer pool holds for the process lifetime | 1 | `main.py` lifespan, `max_size=1` |
| a chunk's hold on one shared worker, average, three captured prod runs | 1.4 s, 2.4 s, 5.7 s | `backend/app/data/demo/*.json` step_seconds.vote over ⌈votes / 25⌉ chunks, captured 2026-09-01 |
| worst single vote measured under 25-way concurrency | 18.9 s (p99 14.0 s) | `first-full-scale-run.md`, 2026-07-28 |
| Render shutdown | SIGTERM, then SIGKILL after 30 s by default | Render deploy docs, read 2026-09-04 |
| most full prod runs a day can buy | 7 | $1.00 daily pool (089) over $0.1373 per 200-vote run (first-full-scale-run.md) |

The chunk holds are derived, not timed at the worker: the captured vote step divided
by the number of 25-vote chunks it took. The 5.7 s run is a full 200-vote buy with no
early stop; the two short ones stopped after 50 votes, and either or both may have
had cached votes. The direct measurement the ticket asked for would need a paid run
with a timer around `_chunk_votes`; the captures bound the same quantity from data
already bought, so none was spent here.

## What the numbers settle

**The executor was the smaller ceiling, by accident, or an unknown one.** By Python's
rule five workers fronted fifteen connections; on a shared host the count is whatever
the kernel reports, which nobody here has read. Either way it was not chosen. With every new connection's `getaddrinfo` in the same pool, a saturated
executor delayed opening connections as well as threaded calls, so the two ceilings
were one, and the wrong one. Sized against the holds above, the cost was seconds:
seven overlapping runs would leave two waiting one chunk, and a newcomer's free
preview or a keep-warm ping would wait about as long. Real, and worth one line.

**The shutdown join is moot on this platform.** `Runner.close()` joins the default
executor for up to 300 s, so an orphaned chunk could in principle hold process exit.
Render sends SIGKILL 30 s after SIGTERM, so the longest a chunk can hold a redeploy
here is 30 s, and the executor's owner does not change that.

**Money bounds concurrency before threads do.** The daily pool buys at most seven
full runs. Concurrency above the pool size would need eight paid runs overlapping
inside one minute, which the day's budget cannot buy.

## Decisions

1. **The shared executor is sized to the pool it fronts.** At startup the loop's
   default executor gets `pooler_pool_size` workers (15 here: 14 request seats and
   the checkpointer's one). It fronts that many connections and must never be the
   smaller ceiling by accident; threads waiting on the network are cheap. The
   executor can still saturate on work that holds no connection — health pings, the
   screener probe, sync graph nodes — and then it **queues, by design**: a thread-pool
   wait is the honest answer for work that is not a request's connection, and no
   status code is owed for it. Stated here so the ticket's "exhaustion answers with a
   status" is read as connections, deliberately. The number is a setting with the dashboard reading as its
   default, because another deployment's dashboard may say otherwise, and the deploy
   guide says where to read it. Tested as behaviour: that many blocking calls run at
   once, and not one more.
2. **Every connection opens under one deadline, 3 s.** `/health` and the seed already
   used it; `get_conn` now does too, from one constant in `db.py`, and as an outer
   `asyncio.timeout` around the whole open, because psycopg resolves the host through
   the shared executor *before* libpq's own timeout starts — the addendum's measured
   DNS wait behind held slots would otherwise sit outside the bound. Evidence the
   number is enough: the keep-warm ping opens a connection under it 120 times a day
   (every 12 min), and the daily check asserts `"db":"up"`. Evidence it is right: at a full pool the pooler would otherwise
   queue the request for a minute, and the waiting screen polls every 3 s per open tab.
3. **Saturation is a status, not a traceback.** A request whose connection cannot
   open answers 503 with one sentence, "The database is busy right now. Try again in
   a moment." The driver's words stay out of it; the exception class goes to the log,
   because a refused password lands on the same path and must not read as a busy pool
   to whoever is on call. Raised where the connection opens, so a connection lost
   mid-query keeps its own error.
4. **No application-side pool, still.** 111/#240 took the pool out for structural
   reasons that stand: the session-scoped advisory lock releases on close and not on
   return, and prepared statements survive the `ALTER TABLE` that invalidates them.
   The pooler is the pool. With the executor at the pool size, the app cannot hold
   more connections than the pooler grants without the 503 above saying so.

## What this does not settle

- The chunk hold is bounded from captures, not timed at the worker. A paid run with a
  timer around `_chunk_votes` would replace the derivation with a measurement.
- Nothing here measures the pooler's queue directly, or what its client sees at the
  end of the minute. The 3 s deadline preempts the queue, which is the point, but the
  queue's own behaviour under this project's plan is quoted from the FAQ, not observed.
- The executor's new size assumes the deployed container keeps one uvicorn worker
  (`Dockerfile`, `--workers 1`). Two workers would front the same fifteen connections
  with thirty threads, and the setting would need halving.
