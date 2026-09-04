"""Turn LangSmith tracing on, when it is configured well enough to work.

LangChain's tracer reads `os.environ`. pydantic-settings parses `.env` into
`Settings` and never writes there, so a key in `.env` would be read by
`Settings`, seen by nothing else, and trace nothing. Exporting closes that gap.

No call site is instrumented: every model call goes through `init_chat_model` /
`init_embeddings` (`app/llm.py`), so the tracer covers the whole app.
"""

import os

from langsmith import utils as ls_utils

from app.config import Settings
from app.config import settings as _settings

# The SDK resolves "is tracing on?" through all four of these, in this order,
# and stops at the first one set. Writing only `LANGSMITH_TRACING` would let an
# environment carrying the older `LANGCHAIN_TRACING_V2=true` trace every run
# while this module reported off — and the reader would see no disclosure.
_SWITCHES = (
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING",
)


def configure_tracing(settings: Settings = _settings) -> bool:
    """Export the tracing configuration, and report whether tracing is really on.

    The return value decides whether readers are warned, so it is read back from
    the SDK rather than inferred from what we just set.
    """
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ.update(
            {
                "LANGSMITH_API_KEY": settings.langsmith_api_key.get_secret_value(),
                "LANGSMITH_PROJECT": settings.langsmith_project,
                "LANGSMITH_ENDPOINT": settings.langsmith_endpoint,
            }
        )
        wanted = "true"
    else:
        wanted = "false"
    # Every switch, not just the one we prefer: any one of them left set the
    # other way decides the answer instead of us.
    for switch in _SWITCHES:
        os.environ[switch] = wanted
    # The SDK memoises its environment lookups, and we have just changed the
    # environment underneath it.
    ls_utils.get_env_var.cache_clear()  # type: ignore[attr-defined]  # overloads hide lru_cache
    return ls_utils.tracing_is_enabled() is True
