"""Tracing is a flag the app runs fine without.

What these tests defend: tracing is on only when it can actually send a trace,
and what is configured is what the SDK ends up reading. LangChain's tracer reads
`os.environ`, and pydantic-settings does not write there, so the export pinned
here is the mechanism rather than a detail.
"""

import os

import pytest

from app.config import Settings
from app.tracing import configure_tracing


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Exports land in a copy of the environment. `monkeypatch.delenv` records
    nothing for a variable that was already absent, so without this the fake key
    these tests set would outlive them."""
    monkeypatch.setattr(os, "environ", dict(os.environ))


_DB = {
    "postgres_user": "u",
    "postgres_password": "p",
    "postgres_db": "d",
}


def _settings(**overrides) -> Settings:
    """Explicit every time: `Settings` also reads the repo's `.env`, so
    inheriting it would make these pass or fail per machine."""
    return Settings(
        **_DB,
        **{
            "langsmith_tracing": False,
            "langsmith_api_key": None,
            "langsmith_project": "test-project",
            "langsmith_endpoint": "https://eu.api.smith.langchain.com",
            **overrides,
        },
    )


def test_the_flag_alone_does_not_turn_tracing_on(monkeypatch) -> None:
    """A key-less deploy with the flag set would build a tracer that fails on
    every model call and shows no trace for any of them."""
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    assert configure_tracing(_settings(langsmith_tracing=True)) is False
    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_a_configured_project_reaches_the_variables_the_sdk_reads(
    monkeypatch,
) -> None:
    """`Settings` can hold a good key from `.env` while `os.environ` — where the
    tracer looks — holds nothing, leaving tracing configured and silent."""
    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)

    assert (
        configure_tracing(
            _settings(langsmith_tracing=True, langsmith_api_key="lsv2-not-a-real-key")
        )
        is True
    )

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "lsv2-not-a-real-key"
    assert os.environ["LANGSMITH_PROJECT"] == "test-project"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://eu.api.smith.langchain.com"
