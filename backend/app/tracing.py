"""Turn LangSmith tracing on, when it is configured well enough to work.

Why this module exists: LangChain's tracer reads `os.environ`, and
pydantic-settings does not write there — it parses `.env` into `Settings` and
stops. A key in `.env` would therefore be read by `Settings`, seen by nothing
else, and trace nothing. Exporting what `Settings` holds closes that gap.

No call site is instrumented. Every model call goes through `init_chat_model` /
`init_embeddings` (`app/llm.py`), so the tracer covers votes, targeting,
screening, the judge and the analyst, and the graph's named nodes become
per-stage spans.
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
        # process environment, and this is the one place that knows the key is
        # missing. Silence here would leave the SDK tracing into a 401.
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
