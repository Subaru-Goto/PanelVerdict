import argparse
import sys

import psycopg
from factories import DIM

from app.config import settings
from app.schemas import Locale
from app.seed import (
    SeedResult,
    _parse_countries,
    add_pool_args,
    build_quotas,
    main,
    seed_pool,
)


class CountingEmbedder:
    """Counts embed() calls, so a test can prove resume does NOT re-assemble."""

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [[float(len(text))] * DIM for text in texts]


def _persona_count(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM personas").fetchone()[0]


def test_seed_pool_persists_all_when_empty(conn):
    embedder = CountingEmbedder()

    result = seed_pool(conn, {Locale.US: 3}, master_seed=1, embedder=embedder)

    assert result == SeedResult(requested=3, written=3, skipped=0)
    assert _persona_count(conn) == 3
    assert embedder.calls == 3


def test_seed_pool_resume_skips_without_reassembling(conn):
    embedder = CountingEmbedder()
    quotas = {Locale.US: 3}

    seed_pool(conn, quotas, master_seed=1, embedder=embedder)
    assert embedder.calls == 3

    # re-run: every persona already present, so nothing is assembled — and nothing
    # is embedded, which is now the only paid call in the pool build
    result = seed_pool(conn, quotas, master_seed=1, embedder=embedder)

    assert result == SeedResult(requested=3, written=0, skipped=3)
    assert embedder.calls == 3
    assert _persona_count(conn) == 3


def test_parse_countries_dedups_preserving_order():
    assert _parse_countries("US,US,JP") == [Locale.US, Locale.JP]


def test_add_pool_args_defines_the_shared_pool_flags_with_defaults():
    # shared by the seed and echo-audit CLIs — the audit must accept the exact
    # flags the seed ran with, or it recomputes examples for the wrong pool
    parser = argparse.ArgumentParser()
    add_pool_args(parser)

    args = parser.parse_args([])

    assert vars(args) == {"size": "dev", "seed": 0, "countries": list(Locale)}


def test_add_pool_args_parses_explicit_values():
    parser = argparse.ArgumentParser()
    add_pool_args(parser)

    args = parser.parse_args(["--size", "full", "--seed", "9", "--countries", "jp,us"])

    assert vars(args) == {
        "size": "full",
        "seed": 9,
        "countries": [Locale.JP, Locale.US],
    }


def test_build_quotas_hits_exact_size_split_across_countries():
    quotas = build_quotas("full", [Locale.US, Locale.JP, Locale.DE])

    assert set(quotas) == {Locale.US, Locale.JP, Locale.DE}
    assert sum(quotas.values()) == 5000  # remainder spread, not dropped
    assert max(quotas.values()) - min(quotas.values()) <= 1


class TestDryRun:
    """Seeding is the other path that spends money, and unlike a sweep it gets
    triggered by a schema change rather than by someone deciding to spend."""

    def _prepare(self, monkeypatch, pg_url: str, *extra: str) -> None:
        monkeypatch.setattr(
            sys, "argv", ["seed", "--size", "dev", "--countries", "US", *extra]
        )
        # database_url is a computed property, so it is patched on the class.
        monkeypatch.setattr(type(settings), "database_url", property(lambda _: pg_url))

    def test_it_reports_the_work_without_generating_or_judging(
        self, conn, pg_url, monkeypatch, capsys
    ):
        def fail(*args, **kwargs):
            raise AssertionError("a dry run must not construct a paid client")

        self._prepare(monkeypatch, pg_url, "--dry-run")
        monkeypatch.setattr("app.seed.OpenRouterEmbedder", fail)
        monkeypatch.setattr("app.seed.OpenRouterJudge", fail)
        main()

        assert "200 personas to generate" in capsys.readouterr().out
        assert _persona_count(conn) == 0

    def test_it_needs_no_api_key(self, conn, pg_url, monkeypatch):
        self._prepare(monkeypatch, pg_url, "--dry-run")
        monkeypatch.setattr(settings, "openrouter_api_key", None)
        main()

    def test_it_discounts_what_the_pool_already_holds(
        self, conn, pg_url, monkeypatch, capsys
    ):
        """Seeding resumes, so the spend is the shortfall rather than the quota —
        a count that ignored the existing pool would overstate every resume."""
        seed_pool(conn, {Locale.US: 3}, master_seed=1, embedder=CountingEmbedder())
        conn.commit()  # main() opens its own connection and cannot see an open txn

        self._prepare(monkeypatch, pg_url, "--dry-run")
        main()
        assert "197 personas to generate" in capsys.readouterr().out
