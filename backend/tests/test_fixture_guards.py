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

from app.config import settings

from tests.factories import make_report


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


def test_a_report_the_factory_builds_is_a_body_a_run_could_emit() -> None:
    """`make_report` replaced a hand-written literal that agreed with
    `EvaluateResponse` in shape and disagreed in fact — `voted: 50` beside
    `votes: []`, `requested: 200` against a profile of 25 (114/#245). The
    factory computes those relations instead; this pins that it keeps doing
    so, and that no container is ever emptied back into unguardability: an
    empty `votes` or `traits` is exactly what let an element-type change
    validate unnoticed.
    """
    report = make_report()

    assert report["counts"]["voted"] == len(report["votes"])
    assert report["tally"]["total"] == len(report["votes"])
    assert sum(report["tally"]["counts"].values()) == report["tally"]["total"]
    assert report["counts"]["requested"] == settings.panel.size

    assert report["votes"], "an empty panel guards no element type"
    assert report["notices"]
    assert report["query"]["notices"]
    assert report["query"]["income_quintiles"]
    assert report["query"]["education"]
    assert report["query"]["traits"]
    assert report["query"]["gender"] is not None

    # Every voter is a member of the panel the query describes.
    for vote in report["votes"]:
        voter = vote["voter"]
        assert voter["country"] in report["query"]["countries"]
        assert voter["gender"] == report["query"]["gender"]
        assert report["query"]["min_age"] <= voter["age"] <= report["query"]["max_age"]
