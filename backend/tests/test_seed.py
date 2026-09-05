import argparse
import sys

import psycopg
import pytest

from app.config import settings
from app.persistence import apply_schema, missing_columns, schema_columns
from app.schemas import Locale
import app.seed as seed_module
from app.seed import (
    SeedResult,
    _parse_countries,
    add_pool_args,
    build_quotas,
    main,
    seed_pool,
)


def _persona_count(conn: psycopg.Connection) -> int:
    return _count(conn, "personas")


def _count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return row[0]


def test_seed_pool_persists_all_when_empty(conn):
    result = seed_pool(conn, {Locale.US: 3}, master_seed=1)

    assert result == SeedResult(requested=3, written=3, skipped=0)
    assert _persona_count(conn) == 3


def test_seed_pool_resume_skips_without_reassembling(conn, monkeypatch):
    quotas = {Locale.US: 3}
    seed_pool(conn, quotas, master_seed=1)

    # re-run: every persona already present, so nothing is assembled. Pinned by
    # counting what `assemble_pool` yields rather than by an embedder — the pool
    # makes no model call at all since 084/#175, so there is no paid call left
    # to count.
    assembled: list[str] = []
    real = seed_module.assemble_pool

    def counting(*args, **kwargs):
        for persona in real(*args, **kwargs):
            assembled.append(persona.id)
            yield persona

    monkeypatch.setattr(seed_module, "assemble_pool", counting)
    result = seed_pool(conn, quotas, master_seed=1)

    assert result == SeedResult(requested=3, written=0, skipped=3)
    assert assembled == []
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


class TestSchemaOnly:
    """CI and a fresh deploy both need the schema and neither wants the seed:
    `--corpus-only` applies schema *and* pays to embed 15 passages on every
    run, and `--dry-run` deliberately refuses to touch schema at all, so there
    was no way to reach the DDL for free (115/#248)."""

    def _prepare(self, monkeypatch, pg_url: str, *extra: str) -> None:
        monkeypatch.setattr(sys, "argv", ["seed", *extra])
        monkeypatch.setattr(type(settings), "database_url", property(lambda _: pg_url))

    def test_it_applies_the_schema_and_pays_for_nothing(
        self, conn, pg_url, monkeypatch, capsys
    ):
        def fail(*args, **kwargs):
            raise AssertionError("applying schema must not construct a paid client")

        monkeypatch.setattr("app.seed.OpenRouterEmbedder", fail)
        monkeypatch.setattr("app.seed.OpenRouterJudge", fail)
        conn.execute("DROP TABLE IF EXISTS corpus_chunks CASCADE")
        conn.commit()
        self._prepare(monkeypatch, pg_url, "--schema-only")

        main()

        # Read from the schema, not written as a number: hand-coding the count
        # is the maintenance trap `_REQUIRED_COLUMNS` was.
        assert f"{len(schema_columns())} tables" in capsys.readouterr().out
        assert missing_columns(conn) == {}
        assert _count(conn, "corpus_chunks") == 0, "the corpus was reseeded"

    def test_it_needs_no_api_key(self, conn, pg_url, monkeypatch):
        self._prepare(monkeypatch, pg_url, "--schema-only")
        monkeypatch.setattr(settings, "openrouter_api_key", None)

        main()

    def test_a_dry_run_applies_nothing(self, conn, pg_url, monkeypatch, capsys):
        """`--schema-only --dry-run` used to apply every statement and take
        ACCESS EXCLUSIVE on every table in `public`, against a flag whose help
        says it writes nothing — the same shape as the `--corpus-only --dry-run`
        bug the comment beside it records fixing (115/#248, review).
        """
        conn.execute("DROP TABLE IF EXISTS corpus_chunks CASCADE")
        conn.commit()
        self._prepare(monkeypatch, pg_url, "--schema-only", "--dry-run")

        main()

        assert "nothing written" in capsys.readouterr().out
        absent = conn.execute(
            "SELECT to_regclass('public.corpus_chunks') IS NULL"
        ).fetchone()
        assert absent is not None and absent[0] is True
        apply_schema(conn)
        conn.commit()

    def test_the_row_level_security_sweep_still_runs(self, conn, pg_url, monkeypatch):
        """The sweep is why additive DDL lives inside `schema.sql` rather than
        beside it. An entry point that applied schema and skipped the sweep
        would leave a new table readable through the data API."""
        conn.execute("DROP TABLE IF EXISTS spend_ledger CASCADE")
        conn.commit()
        self._prepare(monkeypatch, pg_url, "--schema-only")

        main()

        unswept = conn.execute(
            "SELECT relname FROM pg_class c JOIN pg_namespace n"
            " ON n.oid = c.relnamespace WHERE n.nspname = 'public'"
            " AND c.relkind = 'r' AND NOT c.relrowsecurity"
        ).fetchall()
        assert unswept == []


class TestCheckSchema:
    """The CI drift check. Reads and never writes, so the credential it runs
    under can be SELECT-only — nothing automatic can push a wrong migration
    (115/#248, and the least-privilege stance in docs/least-privilege.md)."""

    def _prepare(self, monkeypatch, pg_url: str) -> None:
        monkeypatch.setattr(sys, "argv", ["seed", "--check-schema"])
        monkeypatch.setattr(type(settings), "database_url", property(lambda _: pg_url))

    def test_a_current_database_passes(self, conn, pg_url, monkeypatch, capsys):
        apply_schema(conn)
        conn.commit()
        self._prepare(monkeypatch, pg_url)

        main()

        assert "up to date" in capsys.readouterr().out

    def test_a_missing_column_fails_the_build_and_names_it(
        self, conn, pg_url, monkeypatch
    ):
        apply_schema(conn)
        conn.execute("ALTER TABLE spend_ledger DROP COLUMN usd CASCADE")
        conn.commit()
        try:
            self._prepare(monkeypatch, pg_url)

            with pytest.raises(SystemExit) as exit_info:
                main()

            assert "spend_ledger" in str(exit_info.value)
            assert "usd" in str(exit_info.value)
        finally:
            conn.execute("DROP TABLE spend_ledger CASCADE")
            conn.commit()
            apply_schema(conn)

    def test_it_writes_nothing_at_all(self, conn, pg_url, monkeypatch):
        """The point of a check-only entry point: run it against a database
        missing a whole table and the table is still missing afterwards. A
        check that quietly applied would defeat the manual-apply decision
        (083/#173) and would need a credential that could."""
        conn.execute("DROP TABLE IF EXISTS corpus_chunks CASCADE")
        conn.commit()
        self._prepare(monkeypatch, pg_url)
        try:
            with pytest.raises(SystemExit):
                main()

            exists = conn.execute(
                "SELECT to_regclass('public.corpus_chunks') IS NOT NULL"
            ).fetchone()
            assert exists is not None and exists[0] is False
        finally:
            apply_schema(conn)
            conn.commit()


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
        seed_pool(conn, {Locale.US: 3}, master_seed=1)
        conn.commit()  # main() opens its own connection and cannot see an open txn

        self._prepare(monkeypatch, pg_url, "--dry-run")
        main()
        assert "197 personas to generate" in capsys.readouterr().out


class TestAFullRunWithoutAKey:
    """084/#175: the pool is model-free, so it seeds without a key; the corpus and
    the judge are paid, so their absence is a non-zero exit that says what was
    and was not done — a green exit that skipped the corpus is the deploy
    failure docs/deploy.md already records."""

    def test_it_seeds_the_pool_then_refuses_the_paid_steps_loudly(
        self, conn, pg_url, monkeypatch
    ):
        monkeypatch.setattr(sys, "argv", ["seed", "--size", "dev", "--seed", "0"])
        monkeypatch.setattr(type(settings), "database_url", property(lambda _: pg_url))
        monkeypatch.setattr(settings, "openrouter_api_key", None)

        def fail(*args, **kwargs):
            raise AssertionError("no key: no paid client may be constructed")

        monkeypatch.setattr("app.seed.OpenRouterEmbedder", fail)
        monkeypatch.setattr("app.seed.OpenRouterJudge", fail)

        with pytest.raises(SystemExit) as stop:
            main()

        assert stop.value.code not in (0, None)
        assert _persona_count(conn) > 0, "the free step was not done"
        message = str(stop.value.code)
        assert "pool is seeded" in message
        assert "corpus" in message and "judge" in message
        assert "--corpus-only" in message
