"""The fixtures' own guards, asserted rather than assumed.

These test the harness, which is unusual and deliberate: a guard that silently
stops working takes the failure it was protecting against with it, and the last
one did. `SET lock_timeout` was reverted by the first `rollback()` — verified
working in a fresh transaction, never after one rolled back, which is the case
the suite actually contains.
"""

import time

import psycopg
import pytest


def _lock_timeout(cursor) -> str:
    return cursor.execute("SHOW lock_timeout").fetchone()[0]


def test_the_sync_fixture_carries_a_lock_deadline(conn) -> None:
    assert _lock_timeout(conn) == "5s"


@pytest.mark.anyio
async def test_the_async_fixture_s_deadline_survives_a_rollback(aconn) -> None:
    """The regression that voided the guard. A plain `SET` inside a transaction
    is undone when that transaction rolls back; a connect parameter is not."""
    cur = await aconn.execute("SHOW lock_timeout")
    assert (await cur.fetchone())[0] == "5s"

    await aconn.rollback()

    cur = await aconn.execute("SHOW lock_timeout")
    assert (await cur.fetchone())[0] == "5s"


@pytest.mark.anyio
async def test_ddl_behind_a_reader_fails_instead_of_hanging(conn, aconn) -> None:
    """What the deadline buys: the hang becomes a failing test.

    `aconn` is non-autocommit, so this read holds ACCESS SHARE for the rest of
    the test. Without a deadline the DDL below waits for it until CI's own
    timeout kills the job, and no test fails.
    """
    await aconn.execute("SELECT count(*) FROM personas")

    began = time.perf_counter()
    with pytest.raises(psycopg.errors.LockNotAvailable):
        conn.execute("ALTER TABLE personas ADD COLUMN probe int")

    assert 4 < time.perf_counter() - began < 8
