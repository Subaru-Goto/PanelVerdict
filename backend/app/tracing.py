"""Turn LangSmith tracing on, when it is configured well enough to work.

LangChain's tracer reads `os.environ`. pydantic-settings parses `.env` into
`Settings` and never writes there, so a key in `.env` would be read by
`Settings`, seen by nothing else, and trace nothing. Exporting closes that gap.

No call site is instrumented: every model call goes through `init_chat_model` /
`init_embeddings` (`app/llm.py`), so the tracer covers the whole app.
"""

import os

from app.config import Settings
from app.config import settings as _settings


def configure_tracing(settings: Settings = _settings) -> bool:
    """Export the tracing configuration, and report whether tracing is really on.

    The return value is the honest one — what `/health` reports and what decides
    whether the disclosure line renders — not merely what the flag was set to.
    """
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        # Written, not just left alone: the flag may already be true in the
        # environment, and this is the one place that knows the key is missing.
        os.environ["LANGSMITH_TRACING"] = "false"
        return False
    os.environ.update(
        {
            "LANGSMITH_TRACING": "true",
            "LANGSMITH_API_KEY": settings.langsmith_api_key.get_secret_value(),
            "LANGSMITH_PROJECT": settings.langsmith_project,
            "LANGSMITH_ENDPOINT": settings.langsmith_endpoint,
        }
    )
    return True
