"""What a cancel and a request actually cost, on the async request path. 111/#240.

Written because a review round asserted four things about cancellation and
connection limits, and running them showed three were wrong in one direction and
one wrong in the other. Every number the branch's comments quote comes from here,
so the next person to disagree can re-run it instead of re-arguing it.

Four parts, each answering one question that a comment in `app/` now cites:

- **shield** — does `asyncio.shield` around a paid vote chunk preserve the votes
  when a cancel lands mid-chunk? Driven with uvicorn's own forced-shutdown call,
  `task.cancel(msg=...)`.
- **cleanup** — when a cancel lands, does the request's connection actually get
  closed? Isolated `anyio.CancelScope` first, then end to end through real
  uvicorn with a client that walks away mid-stream. The two disagree, and the
  end-to-end one is the one that counts.
- **locks** — is a session advisory lock released when the connection closes,
  including from an aborted transaction? And does a transaction-scoped lock
  survive the vote loop's per-chunk commits?
- **ceiling** — how many Postgres backends are live under N concurrent requests,
  sync-handler shape versus async? The claim under test is that anyio's
  `CapacityLimiter(40)` bounded connections before the conversion.

Needs Docker (testcontainers) and nothing else: no model calls, no money.

    uv run python -m experiments.cancellation_and_connections --part all
"""

import argparse
import asyncio
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import anyio
import httpx
import psycopg
import uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from testcontainers.postgres import PostgresContainer

HOLD_SECONDS = 1.5
REQUESTS = 60
# Long enough that a cancel can be aimed inside it, short enough to keep the
# whole harness under a minute. Nothing is measured in these seconds themselves.
CHUNK_SECONDS = 0.25


def report(line: str) -> None:
    print(line, flush=True)


# --- shield -----------------------------------------------------------------


async def part_shield(url: str) -> None:
    """Shielded chunk versus plainly awaited, under a forced-shutdown cancel."""
    report("\n## shield: does a shielded chunk keep its paid votes?")
    for label, shielded in (("plain await   ", False), ("asyncio.shield", True)):
        async with await psycopg.AsyncConnection.connect(url) as setup:
            await setup.execute("DROP TABLE IF EXISTS probe_votes")
            await setup.execute("CREATE TABLE probe_votes (chunk int)")
            await setup.commit()
        notes: list[str] = []

        async def chunk(conn: psycopg.AsyncConnection, i: int) -> None:
            # The paid part: uncancellable, as `asyncio.to_thread(llm.vote)` is.
            await asyncio.to_thread(time.sleep, CHUNK_SECONDS)
            try:
                await conn.execute("INSERT INTO probe_votes VALUES (%s)", (i,))
                await conn.commit()
                notes.append(f"chunk {i} paid and stored")
            except BaseException as failed:  # noqa: BLE001 — reporting, not handling
                notes.append(f"chunk {i} paid, store failed: {type(failed).__name__}")

        async def handler() -> None:
            async with await psycopg.AsyncConnection.connect(url) as conn:
                for i in range(4):
                    if shielded:
                        await asyncio.shield(chunk(conn, i))
                    else:
                        await chunk(conn, i)

        task = asyncio.create_task(handler())
        await asyncio.sleep(CHUNK_SECONDS * 1.6)
        task.cancel(msg="Task cancelled, timeout graceful shutdown exceeded")
        try:
            await task
        except asyncio.CancelledError:
            notes.append("handler ended cancelled")
        await asyncio.sleep(CHUNK_SECONDS * 3)

        async with await psycopg.AsyncConnection.connect(url) as probe:
            cur = await probe.execute("SELECT count(*) FROM probe_votes")
            stored = (await cur.fetchone())[0]
        report(f"  {label}: {stored} chunk(s) stored | " + "; ".join(notes))


# --- cleanup ----------------------------------------------------------------


async def part_cleanup(url: str) -> None:
    """Isolated cancel scope, then the same question end to end."""
    report("\n## cleanup: is the request's connection closed when a cancel lands?")

    held: dict[str, object] = {}

    async def body() -> None:
        async with await psycopg.AsyncConnection.connect(url) as conn:
            held["conn"] = conn
            await conn.execute("SELECT 1")  # leaves an open transaction
            await anyio.sleep(5)

    with anyio.CancelScope() as scope:
        async with anyio.create_task_group() as tg:
            tg.start_soon(body)
            await anyio.sleep(0.2)
            scope.cancel()
    conn = held["conn"]
    report(
        f"  bare anyio.CancelScope: conn.closed = {conn.closed}"
        "  <- __aexit__'s rollback hits a cancelled scope, so close() is skipped"
    )
    await conn.close()

    report("  end to end, real uvicorn, client walks away mid-stream:")
    events: list[str] = []
    app = FastAPI()

    async def get_conn():
        async with await psycopg.AsyncConnection.connect(url) as conn:
            yield conn
        events.append("dependency exit completed")

    @app.get("/stream")
    async def stream(conn: psycopg.AsyncConnection = Depends(get_conn)):
        async def lines():
            cur = await conn.execute("SELECT pg_backend_pid()")
            yield f"pid={(await cur.fetchone())[0]}\n".encode()
            try:
                for _ in range(50):
                    await asyncio.sleep(0.2)
                    yield b"tick\n"
            except BaseException as raised:  # noqa: BLE001 — reporting
                events.append(f"stream raised {type(raised).__name__}")
                raise

        return StreamingResponse(lines(), media_type="text/plain")

    port = 8771
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)

    def walk_away() -> None:
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        sock.sendall(b"GET /stream HTTP/1.1\r\nHost: x\r\n\r\n")
        sock.recv(4096)
        time.sleep(0.5)
        sock.close()

    await asyncio.to_thread(walk_away)
    await asyncio.sleep(1.5)
    async with await psycopg.AsyncConnection.connect(url) as probe:
        cur = await probe.execute(
            "SELECT count(*) FROM pg_stat_activity"
            " WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
        left = (await cur.fetchone())[0]
    report(f"    events: {events}")
    report(f"    backends still live afterwards (the probe's own excluded): {left}")
    server.should_exit = True
    await asyncio.sleep(1.0)


# --- locks ------------------------------------------------------------------


async def part_locks(url: str) -> None:
    report("\n## locks: what releases an advisory lock?")
    key = "resume:probe"

    async def advisory_held() -> int:
        async with await psycopg.AsyncConnection.connect(url) as probe:
            cur = await probe.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
                " AND objid = (hashtext(%s)::bigint & 4294967295)",
                (key,),
            )
            return (await cur.fetchone())[0]

    conn = await psycopg.AsyncConnection.connect(url)
    await conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (key,))
    await conn.commit()
    try:
        await conn.execute("SELECT 1 / 0")
    except psycopg.Error:
        pass
    report(
        f"  session lock, transaction aborted, connection open: {await advisory_held()}"
    )
    try:
        await conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))
        report("  unlock from an aborted transaction: succeeded")
    except psycopg.Error as failed:
        report(f"  unlock from an aborted transaction: {type(failed).__name__}")
    await conn.close()
    report(f"  session lock after the connection closed: {await advisory_held()}")

    xact = 67890
    async with await psycopg.AsyncConnection.connect(url) as owner:
        await owner.execute("SELECT pg_advisory_xact_lock(%s)", (xact,))
        async with await psycopg.AsyncConnection.connect(url) as probe:
            cur = await probe.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
                " AND objid = %s",
                (xact,),
            )
            report(f"  xact lock before a commit: {(await cur.fetchone())[0]}")
            await owner.commit()
            cur = await probe.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'"
                " AND objid = %s",
                (xact,),
            )
            report(
                f"  xact lock after one commit:  {(await cur.fetchone())[0]}"
                "  <- why the resume lock is session-scoped"
            )


# --- ceiling ----------------------------------------------------------------


def _sync_app(url: str) -> FastAPI:
    """`main`'s shape: sync handler, sync generator dependency."""
    app = FastAPI()

    def get_conn():
        with psycopg.connect(url) as conn:
            yield conn

    @app.get("/w")
    def work(conn: psycopg.Connection = Depends(get_conn)):
        conn.execute("SELECT 1")
        time.sleep(HOLD_SECONDS)
        return {"ok": True}

    return app


def _async_app(url: str) -> FastAPI:
    """This branch's shape."""
    app = FastAPI()

    async def get_conn():
        async with await psycopg.AsyncConnection.connect(url) as conn:
            yield conn

    @app.get("/w")
    async def work(conn: psycopg.AsyncConnection = Depends(get_conn)):
        await conn.execute("SELECT 1")
        await asyncio.sleep(HOLD_SECONDS)
        return {"ok": True}

    return app


def part_ceiling(url: str) -> None:
    report(
        f"\n## ceiling: peak live backends under {REQUESTS} concurrent requests"
        f" holding {HOLD_SECONDS}s each"
    )
    with psycopg.connect(url, autocommit=True) as conn:
        limit = conn.execute("SHOW max_connections").fetchone()[0]
    report(f"  server max_connections = {limit}, anyio default thread limiter = 40")

    for label, build, port in (
        ("sync handler + sync dep (main)  ", _sync_app, 8781),
        ("async handler + async dep       ", _async_app, 8782),
    ):
        peak = [0]
        stop = threading.Event()

        def watch() -> None:
            with psycopg.connect(url, autocommit=True) as probe:
                while not stop.is_set():
                    live = probe.execute(
                        "SELECT count(*) FROM pg_stat_activity"
                        " WHERE datname = current_database()"
                        " AND pid <> pg_backend_pid()"
                    ).fetchone()[0]
                    peak[0] = max(peak[0], live)
                    time.sleep(0.02)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        server = uvicorn.Server(
            uvicorn.Config(build(url), host="127.0.0.1", port=port, log_level="error")
        )
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.05)

        began = time.perf_counter()
        with ThreadPoolExecutor(max_workers=REQUESTS) as pool:
            codes = list(
                pool.map(
                    lambda _: (
                        httpx.get(f"http://127.0.0.1:{port}/w", timeout=120).status_code
                    ),
                    range(REQUESTS),
                )
            )
        elapsed = time.perf_counter() - began
        stop.set()
        watcher.join()
        report(
            f"  {label}: {codes.count(200)}/{REQUESTS} ok,"
            f" peak {peak[0]} backends, wall {elapsed:.1f}s"
        )
        server.should_exit = True
        time.sleep(1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--part",
        choices=("shield", "cleanup", "locks", "ceiling", "all"),
        default="all",
    )
    args = parser.parse_args()

    # pgvector's image rather than stock postgres, to match the suite's fixture.
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        url = pg.get_connection_url(driver=None)
        if args.part in ("shield", "all"):
            asyncio.run(part_shield(url))
        if args.part in ("cleanup", "all"):
            asyncio.run(part_cleanup(url))
        if args.part in ("locks", "all"):
            asyncio.run(part_locks(url))
        if args.part in ("ceiling", "all"):
            part_ceiling(url)


if __name__ == "__main__":
    main()
