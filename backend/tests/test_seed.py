import psycopg
from factories import DIM

from app.schemas import InterestSynthesis, Locale
from app.seed import SeedResult, _parse_countries, build_quotas, seed_pool

_INTERESTS = ["trail running", "home cooking", "indie podcasts"]


class CountingInterestLLM:
    """Counts generate() calls, so a test can prove resume does NOT re-assemble."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, prompt: str) -> InterestSynthesis:
        self.calls += 1
        return InterestSynthesis(interests=list(_INTERESTS))


class FirstSlotFailsLLM:
    """Invalid batches for the first persona's 3 attempts, then valid ones —
    exactly one persona fails generation, the rest succeed."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, prompt: str) -> InterestSynthesis:
        self.calls += 1
        if self.calls <= 3:
            return InterestSynthesis(interests=["too", "few"])
        return InterestSynthesis(interests=list(_INTERESTS))


class StubEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] * DIM for text in texts]


def _persona_count(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM personas").fetchone()[0]


def test_seed_pool_persists_all_when_empty(conn):
    llm = CountingInterestLLM()
    result = seed_pool(
        conn, {Locale.US: 3}, master_seed=1, llm=llm, embedder=StubEmbedder()
    )

    assert result == SeedResult(requested=3, written=3, skipped=0, failed=0)
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

    assert result == SeedResult(requested=3, written=0, skipped=3, failed=0)
    assert llm.calls == 3
    assert _persona_count(conn) == 3


def test_seed_pool_counts_generation_failures_separately_from_skips(conn):
    result = seed_pool(
        conn,
        {Locale.US: 3},
        master_seed=1,
        llm=FirstSlotFailsLLM(),
        embedder=StubEmbedder(),
    )

    # a failed persona is not a resume-skip: the pool is genuinely short
    assert result == SeedResult(requested=3, written=2, skipped=0, failed=1)
    assert _persona_count(conn) == 2


def test_parse_countries_dedups_preserving_order():
    assert _parse_countries("US,US,JP") == [Locale.US, Locale.JP]


def test_build_quotas_hits_exact_size_split_across_countries():
    quotas = build_quotas("full", [Locale.US, Locale.JP, Locale.DE])

    assert set(quotas) == {Locale.US, Locale.JP, Locale.DE}
    assert sum(quotas.values()) == 5000  # remainder spread, not dropped
    assert max(quotas.values()) - min(quotas.values()) <= 1
