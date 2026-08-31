import os

# Before any `app` import: `app.config` reads `.env` at import, and a real
# environment variable outranks that file. Without this, a developer with
# tracing switched on ships a trace for every test run — dashboard noise, and
# free-tier quota spent on stubs. The suite never traces, on anyone's machine.
#
# All four names, because the SDK stops at the first one set and the older
# `LANGCHAIN_*` pair outranks the one we would rather write.
for _switch in (
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING",
):
    os.environ[_switch] = "false"

from typing import Literal  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

from pgvector.psycopg import register_vector_async  # noqa: E402

from app.persistence import prepare_connection, schema_columns  # noqa: E402
from app.vote import VoteResponse  # noqa: E402
from tests.factories import voted  # noqa: E402


class StubLLM:
    """A PanelLLM double returning a fixed vote for every call — no network."""

    configuration = "stub"

    def __init__(self, chosen: Literal["option_1", "option_2"], reason: str = "stub"):
        self._chosen = chosen
        self._reason = reason

    def vote(
        self,
        *,
        system_prompt: str,
        option_1: str,
        option_2: str,
        enacted: str = "",
    ) -> VoteResponse:
        return voted(self._chosen, self._reason)


@pytest.fixture
def stub_llm() -> type[StubLLM]:
    return StubLLM


# A lock this suite waits on is a mistake, not a wait: nothing here legitimately
# queues behind another session. Without it the mistake is a *hang* — a
# non-autocommit read through `aconn` holds ACCESS SHARE for the rest of the
# test, and DDL through `conn` in the same test then blocks until CI's own
# timeout kills the job, with no failing test to point at. Five seconds is
# generous against a suite whose longest legitimate lock wait is none.
#
# On both connections, not just the reader: the timeout has to be set on the
# session that *waits*, and either one can be it.
#
# A libpq connection parameter, not a `SET` statement, and that is the whole
# point: Postgres reverts a plain `SET` issued inside a transaction that then
# rolls back, so the first `await aconn.rollback()` put the deadline back to 0
# and voided the guard — in `test_paid_votes_survive_the_run_dying_before_the_
# response`, which is precisely a test that rolls back. Set at connect it is
# session state no transaction can undo.
_LOCK_TIMEOUT_OPTION = "-c lock_timeout=5s"


@pytest.fixture(scope="module")
def pg_url():
    # pgvector image, not stock postgres — the stock image lacks the extension.
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg.get_connection_url(driver=None)


@pytest.fixture
def anyio_backend():
    """One backend, asyncio — the app runs under uvicorn, and testing a second
    event-loop implementation would test anyio rather than this code."""
    return "asyncio"


@pytest.fixture
async def aconn(pg_url, conn):
    """The async twin of `conn`, for the request path 111/#240 converted.

    It depends on `conn` rather than preparing its own database so there is one
    truncation per test, not two racing ones — and so a test that seeds through
    the sync connection and reads through this one is using a database both
    agree about.

    **Seed with `conn` and commit before reading here.** Two connections are two
    sessions, so an uncommitted write is invisible across them. That is a real
    constraint rather than an oversight: the writers are `persist_pool` and
    friends, which belong to the seed — a script with no event loop — and
    giving them async twins to spare tests a `commit()` would shape production
    code around the suite.
    """
    async with await psycopg.AsyncConnection.connect(
        pg_url, options=_LOCK_TIMEOUT_OPTION
    ) as connection:
        await register_vector_async(connection)
        yield connection


@pytest.fixture
def conn(pg_url):
    # Autocommit: isolation between tests comes from the truncation above, not
    # from a rolled-back transaction — and since 111/#240 a test may seed here
    # and read through `aconn`, a second session that cannot see an uncommitted
    # write. Leaving it off made setup invisible to half the suite.
    with psycopg.connect(
        pg_url, autocommit=True, options=_LOCK_TIMEOUT_OPTION
    ) as connection:
        prepare_connection(connection)
        # Every table the schema declares, read out of `schema.sql` rather than
        # named here: the hand-kept list of five silently missed `tests` when it
        # was added, so reports leaked between tests and one of them failed only
        # when the whole file ran (117/#252). Same drift the completeness probe
        # stopped being subject to in 115/#248.
        #
        # CASCADE is not enough on its own — `votes` has no FK to `personas`, so
        # the ledger must survive a pool reseed — which is why this truncates
        # every table rather than the roots.
        connection.execute(f"TRUNCATE {', '.join(sorted(schema_columns()))} CASCADE")
        connection.commit()
        yield connection
