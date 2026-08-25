"""Tracing is a flag the app runs fine without.

What these tests defend: tracing is on only when it can actually send a trace,
and what is configured is what the SDK ends up reading. LangChain's tracer reads
`os.environ`, and pydantic-settings does not write there, so the export pinned
here is the mechanism rather than a detail.
"""

import os

from app.config import Settings
from app.tracing import configure_tracing

_DB = {
    "postgres_user": "u",
    "postgres_password": "p",
    "postgres_db": "d",
}


def _settings(**overrides) -> Settings:
    """Explicit every time: `Settings` also reads the repo's own `.env`, and a
    test that inherited the developer's real tracing config would pass or fail
    depending on whose machine ran it."""
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
    """The one that matters: a key-less deploy with the flag set would build a
    tracer that fails on every model call — errors on the hot path, and not one
    trace to show for them. Half-configured reads as off, not as on."""
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    assert configure_tracing(_settings(langsmith_tracing=True)) is False
    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_a_configured_project_reaches_the_variables_the_sdk_reads(
    monkeypatch,
) -> None:
    """The gap this module exists to close. `Settings` can hold a perfectly good
    key from the `.env` file while `os.environ` — the only place LangChain's
    tracer looks — holds nothing, so tracing is configured and silent."""
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
