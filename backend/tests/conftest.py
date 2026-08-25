import os

# Before any `app` import: `app.config` reads `.env` at import, and a real
# environment variable outranks that file. Without this, a developer with
# tracing switched on ships a trace for every test run — dashboard noise, and
# free-tier quota spent on stubs. The suite never traces, on anyone's machine.
os.environ["LANGSMITH_TRACING"] = "false"

from typing import Literal

import psycopg
import pytest
from app.persistence import prepare_connection
from app.vote import VoteResponse
from testcontainers.postgres import PostgresContainer
from tests.factories import voted


class StubLLM:
    """A PanelLLM double returning a fixed vote for every call — no network."""

    configuration = "stub"

    def __init__(self, chosen: Literal["option_1", "option_2"], reason: str = "stub"):
        self._chosen = chosen
        self._reason = reason

    def vote(self, *, system_prompt: str, option_1: str, option_2: str) -> VoteResponse:
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
