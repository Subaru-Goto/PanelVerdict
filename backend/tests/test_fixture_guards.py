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

from app.schemas import EducationLevel, Locale

from tests.factories import make_panel_vote, make_report


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


def _empty_containers(value, path: str = "") -> list[str]:
    """Every empty list, dict or tuple in a dumped report, by path.

    Walked rather than enumerated by name: a container field added to
    `EvaluateResponse` or `TargetQuery` later arrives as pydantic's empty
    default, which is the same silent-default path that let the literal this
    factory replaced rot unnoticed (114/#245).
    """
    if isinstance(value, dict):
        if not value:
            return [path]
        return [
            found
            for key, item in value.items()
            for found in _empty_containers(item, f"{path}.{key}" if path else key)
        ]
    if isinstance(value, list | tuple):
        if not value:
            return [path]
        return [
            found
            for index, item in enumerate(value)
            for found in _empty_containers(item, f"{path}[{index}]")
        ]
    return []


@pytest.mark.parametrize(
    "votes",
    [
        None,
        # A caller-supplied panel, and deliberately not the default's: the
        # derivation is only worth something if it follows the votes it was
        # given, and a guard that only ever checks the default build cannot
        # tell a derived query from a hardcoded one.
        [
            make_panel_vote(
                "US-1", country=Locale.US, education=EducationLevel.SECONDARY
            ),
            make_panel_vote(
                "US-2", country=Locale.US, education=EducationLevel.SECONDARY
            ),
        ],
    ],
    ids=["default panel", "caller's own panel"],
)
def test_a_report_the_factory_builds_is_a_body_a_run_could_emit(votes) -> None:
    """`make_report` replaced a hand-written literal that agreed with
    `EvaluateResponse` in shape and disagreed in fact — `voted: 50` beside
    `votes: []`, `requested: 200` against a profile of 25 (114/#245). The
    factory derives those relations instead; this pins that it keeps doing so.
    """
    report = make_report(votes=votes)

    assert report["counts"]["voted"] == len(report["votes"])
    assert report["tally"]["total"] == len(report["votes"])
    assert sum(report["tally"]["counts"].values()) == report["tally"]["total"]
    assert report["counts"]["requested"] == settings.panel.size
    assert set(report["tally"]["counts"]) == set(report["variants"])
    assert report["query"]["gender"] is not None

    # Every voter is a member of the panel the query describes — the check that
    # makes the derivation worth anything, since a report claiming a Japan-only
    # panel of Americans is a body no run emits.
    query = report["query"]
    for vote in report["votes"]:
        voter = vote["voter"]
        assert voter["country"] in query["countries"]
        assert voter["gender"] == query["gender"]
        assert voter["education"] in query["education"]
        assert query["min_age"] <= voter["age"] <= query["max_age"]
        for request in query["traits"]:
            assert voter["traits"][request["trait"]] == request["level"]


def test_the_factory_leaves_no_container_empty_for_a_type_change_to_hide() -> None:
    """An empty list or dict has no element, so retyping one — `tuple[int, ...]`
    to a string enum, `traits` to a submodel — validates with nothing to notice.
    That is the second half of what the literal got wrong, and it is a claim
    about the whole body rather than the fields anyone thought to list.
    """
    assert _empty_containers(make_report()) == []


def test_the_factory_refuses_the_bodies_it_exists_to_abolish() -> None:
    """The two ways a caller could reintroduce the mismatch: an empty panel
    (`voted: 0` beside `votes: []`, and no element to guard), and a vote for a
    variant the panel was never shown. Both are answered before the body is
    built, naming the fix — a `KeyError` from inside a factory tells a reader
    nothing.
    """
    with pytest.raises(ValueError, match="at least one vote"):
        make_report(votes=[])

    with pytest.raises(ValueError, match="no variant offers"):
        make_report(votes=[make_panel_vote("p-1", chosen="c")])
