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

from app.persistence import prepare_connection  # noqa: E402
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


@pytest.fixture(scope="module")
def pg_url():
    # pgvector image, not stock postgres — the stock image lacks the extension.
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg.get_connection_url(driver=None)


@pytest.fixture
def conn(pg_url):
    with psycopg.connect(pg_url) as connection:
        prepare_connection(connection)
        # votes has no FK to personas (the ledger must survive a pool reseed), so
        # CASCADE alone would leave cache rows leaking between tests.
        connection.execute(
            "TRUNCATE personas, votes, request_ledger, spend_ledger CASCADE"
        )
        connection.commit()
        yield connection
