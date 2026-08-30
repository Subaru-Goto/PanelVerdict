# What a cancel and a request actually cost on the async request path

**Run 2026-08-27**, no paid calls — Docker and a throwaway Postgres. Harness:
`backend/experiments/cancellation_and_connections.py` (`--part all`, about a
minute). Ticket: 111/#240, feeding 112/#242.

Headline: **of five claims the branch's review rounds asserted about cancellation
and connection limits, four were wrong and one was right.** The four break down as
three pessimistic — each about to buy a fix for a problem that does not exist —
and one optimistic, a shield asserted to protect paid votes that protected
nothing. The fifth, an aborted transaction masking the caller's error, was
correct and was the round's one live defect; it is fixed. Every figure the
branch's comments quote is from this run.

## What was claimed, and what ran

| Claim | Measured |
|---|---|
| `asyncio.shield` protects a paid vote chunk from a mid-run cancel | **False.** Same votes stored either way; the shield adds a write to a closed connection |
| A cancel skips `AsyncConnection.__aexit__`'s `close()`, leaking a backend per disconnect | **False end to end.** True of a bare `anyio.CancelScope`, but FastAPI unwinds the dependency outside the cancelled scope |
| A cancel skips `_only_one_answer`'s unlock, leaving a run un-resumable until it expires | **False.** Closing the connection releases a session lock, and the connection does close |
| An *aborted transaction* makes that unlock raise, replacing the caller's error | **True** — the one real defect here |
| anyio's `CapacityLimiter(40)` bounded live connections before the conversion | **False.** 60 concurrent requests opened 60 backends in *both* shapes |

## shield: the shield preserved nothing

Driven with uvicorn's own forced-shutdown call, `task.cancel(msg="Task
cancelled, timeout graceful shutdown exceeded")`, aimed inside the second chunk:

```
plain await   : 1 chunk stored | chunk 0 paid and stored; handler ended cancelled
asyncio.shield: 1 chunk stored | chunk 0 paid and stored; handler ended cancelled;
                                 chunk 1 paid, store failed: OperationalError
```

Shielding the chunk does not stop the *awaiter* being cancelled — that is what a
shield permits. So the handler unwinds, `get_conn` closes the connection, and the
detached chunk reaches a closed one. Identical votes preserved, plus an error and
a chunk outliving its request. Removed.

Worth stating plainly: **nothing cancels `/evaluate` in this deployment today.**
Uvicorn's `timeout_graceful_shutdown` defaults to `None` and the Dockerfile does
not set it, so `asyncio.wait_for(..., timeout=None)` waits for the handler
indefinitely; the escalation is the platform's SIGKILL, which no Python code
survives. The shield was insurance against an event that cannot arrive, priced in
a worse failure if it did.

## cleanup: the leak is real in isolation and absent in the app

A bare cancelled `anyio.CancelScope` does skip the close — `__aexit__` guards
`rollback()` with `except Exception`, and `CancelledError` is a `BaseException`,
so `close()` never runs and the backend stays live. That is where the claim came
from, and it is correct about psycopg.

It does not survive the real stack. `/chat` is a `StreamingResponse` holding the
request's connection, and Starlette cancels the streaming task group's scope when
a reader walks away (`starlette/responses.py`). Through real uvicorn, with a raw
socket that reads one chunk and closes:

```
events: ['stream raised CancelledError', 'dependency exit completed']
backends still live afterwards: 0
```

FastAPI unwinds its dependency `AsyncExitStack` *outside* the cancelled scope, so
the cleanup awaits run uncancelled. No shielded close is needed, and adding one
would have been a fix with a passing test and no defect under it.

## locks: session scope is right, and the `finally` was not

```
session lock, transaction aborted, connection open: 1
unlock from an aborted transaction: InFailedSqlTransaction
session lock after the connection closed:          0
xact lock before a commit: 1
xact lock after one commit: 0
```

Three things follow. The transaction-scoped lock that looked like the structural
answer is released by the *first* commit, and the vote loop commits per chunk —
which is why `_only_one_answer` chose session scope, now measured rather than
reasoned. Closing the connection releases the session lock even from an aborted
transaction, so the explicit unlock is belt to the connection's braces. And the
unlock raises `InFailedSqlTransaction` on an aborted transaction, *during handling
of* whatever the run was already failing with — so `_run_graph`'s curated 402,
422 or 502 reached the client as an opaque 500. That one was a live defect: the
`finally` now gives up quietly and logs.

## ceiling: there was never a 40-connection ceiling

60 concurrent requests, each holding its connection for 1.5s, against
`max_connections = 100`:

```
sync handler + sync dep (main)  : 60/60 ok, peak 60 backends, wall ~3.2s
async handler + async dep       : 60/60 ok, peak 60 backends, wall ~1.7s
```

Wall time moves by a tenth or two between runs; the count does not, and neither
does the shape — two waves against one.

Sixty live backends in both shapes. The limiter was working — 60 holds of 1.5s
took two waves synchronously and one asynchronously, which is exactly 40 slots
showing up in wall time — but it bounded concurrent handler *bodies*, never open
connections. A sync generator dependency borrows a threadpool slot only for
`__enter__`/`__exit__`, and dependencies are solved before the handler queues for
a slot of its own, so every queued request already held a connection.

So the conversion removed a throughput bound, not a connection bound. 112/#242's
question is unchanged and stands on its own terms: **what will the Supabase
session pooler actually grant?** Neither shape bounds connections, so that number
was needed before this branch as well.

**That is not the same as the conversion being free, and this section measured
only connections.** The blocking work moved *into* a pool this run also asked
about, and it is the smaller one:

```
anyio default thread limiter (bounded a sync handler) : 40
asyncio default executor (bounds every to_thread now) : 14   -- min(32, cpu+4)
```

`min(32, cpu+4)` is 5 on a 1-vCPU container. Every `asyncio.to_thread` site shares
it, and so does LangGraph's dispatch of every sync node — and so does
`loop.getaddrinfo`, which `psycopg.AsyncConnection.connect` awaits, so a saturated
executor delays *new connections* as well as threaded calls. Nothing here
measures that pool under load; it belongs to #242 along with the pooler budget,
and the comment on that ticket carries what has been measured so far.

## What this cannot see

- One machine, one uvicorn worker, a local container. It measures *mechanism* —
  which cleanup runs, which lock survives, whether a bound exists — not what the
  Supabase pooler grants or how it behaves under loss. That is #242's, and this
  harness deliberately does not guess at it.
- `--part cleanup` proves the current FastAPI, Starlette and psycopg versions
  unwind the dependency outside the cancelled scope. It is a fact about those
  libraries, not a guarantee they owe us, and an upgrade should re-run this part.
  The versions that were actually resolved are in `backend/uv.lock` —
  `pyproject.toml` carries only `>=` floors and does not name Starlette at all.
- The harness apps carry the deployment's middleware — `BaseHTTPMiddleware` via
  `@app.middleware("http")`, then `CORSMiddleware` — because
  `BaseHTTPMiddleware` runs the downstream app in its own task group and pumps
  the body over a memory object stream, which is where streaming cancellation
  ordering could plausibly differ. Measured with and without: same result, no
  leak either way. It was a bare app for the first three runs of this document,
  and that was a real gap rather than a safe simplification.
- Nothing here says what a redeploy mid-run costs a paying caller. The in-flight
  chunk is lost, and the per-chunk ledger means earlier chunks are not — but the
  size of that loss in real votes has not been measured.
