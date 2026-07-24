import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from app.persistence import prepare_connection
from app.schemas import InterestSynthesis, Locale
from app.seed import SeedResult, build_quotas, seed_pool

_DIM = 1536
_INTERESTS = ["trail running", "home cooking", "indie podcasts"]


class CountingInterestLLM:
    """Counts generate() calls, so a test can prove resume does NOT re-assemble."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, prompt: str) -> InterestSynthesis:
        self.calls += 1
        return InterestSynthesis(interests=list(_INTERESTS))


class StubEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] * _DIM for text in texts]


@pytest.fixture(scope="module")
def pg_url():
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg.get_connection_url(driver=None)


@pytest.fixture
def conn(pg_url):
    with psycopg.connect(pg_url) as connection:
        prepare_connection(connection)
        connection.execute("TRUNCATE personas CASCADE")
        connection.commit()
        yield connection


def _persona_count(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM personas").fetchone()[0]


def test_seed_pool_persists_all_when_empty(conn):
    llm = CountingInterestLLM()
    result = seed_pool(
        conn, {Locale.US: 3}, master_seed=1, llm=llm, embedder=StubEmbedder()
    )

    assert result == SeedResult(requested=3, written=3, skipped=0)
    assert _persona_count(conn) == 3
    assert llm.calls == 3


def test_seed_pool_resume_skips_without_reassembling(conn):
    llm = CountingInterestLLM()
    embedder = StubEmbedder()
    quotas = {Locale.US: 3}

    seed_pool(conn, quotas, master_seed=1, llm=llm, embedder=embedder)
    assert llm.calls == 3

    # re-run: every persona already present, so nothing is assembled — no new LLM
    # calls (the whole point of skipping existing ids before assembly)
    result = seed_pool(conn, quotas, master_seed=1, llm=llm, embedder=embedder)

    assert result == SeedResult(requested=3, written=0, skipped=3)
    assert llm.calls == 3
    assert _persona_count(conn) == 3


def test_build_quotas_hits_exact_size_split_across_countries():
    quotas = build_quotas("full", [Locale.US, Locale.JP, Locale.DE])

    assert set(quotas) == {Locale.US, Locale.JP, Locale.DE}
    assert sum(quotas.values()) == 5000  # remainder spread, not dropped
    assert max(quotas.values()) - min(quotas.values()) <= 1
