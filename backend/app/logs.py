"""Structured logging (047/#145): one JSON object per line, with the ids that
place it.

Two ids travel beside every line, both read from context variables so a call
site does not need to know them:

- ``request_id`` — minted at the edge for every request, including the ones a
  401, a 429 or a refused screen turns away before any run exists.
- ``thread_id`` — the run's id: the checkpointer's thread, minted before
  screening and surviving the pause at the panel gate, so the two requests of
  one run share it. Not ``test_id``, which the ledger keeps as *provenance*: a
  cached vote carries the id of the run that paid for it.
"""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_thread_id: ContextVar[str | None] = ContextVar("thread_id", default=None)


@contextmanager
def bind_request(request_id: str) -> Iterator[None]:
    """Every line logged inside carries this request id."""
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


@contextmanager
def bind_thread(thread_id: str) -> Iterator[None]:
    """Every line logged inside carries this run's thread id."""
    token = _thread_id.set(thread_id)
    try:
        yield
    finally:
        _thread_id.reset(token)


class ContextStamp(logging.Filter):
    """Stamp the bound ids onto the record, null when nothing is bound.

    A filter rather than the formatter's job so the ids are read in the thread
    that logged — the emitting thread's context — and so any handler, a test's
    capture included, sees them on the record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # A call site that names its own id wins: the analyst's usage line is
        # written while the response streams, after the request's bind ended.
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get()
        if not hasattr(record, "thread_id"):
            record.thread_id = _thread_id.get()
        return True


# What every record carries by construction. Anything else on a record was
# passed as `extra=` by the call site and is a field of the event — except
# `color_message`, uvicorn's ANSI-coloured copy of its own message.
_RECORD_ATTRIBUTES = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    """Render a record as one JSON object on one line.

    Fields passed as ``extra=`` become top-level keys, so a number logged as a
    field can be queried as one.
    """

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RECORD_ATTRIBUTES:
                event[key] = value
        if record.exc_info:
            # The traceback stays inside the object: one line per event holds
            # even when the event is a crash.
            event["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            event["stack"] = self.formatStack(record.stack_info)
        try:
            return json.dumps(event, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # A field json cannot walk (a self-referencing object, say) must
            # not cost the event: the handler would drop the record and print
            # a plain-text traceback into the JSON stream.
            return json.dumps(
                {key: repr(value) for key, value in event.items()}, ensure_ascii=False
            )


class RequestIdMiddleware:
    """Mint the id every line of a request is logged under, and return it as
    ``X-Request-ID`` so a reader holding a response can find its lines.

    Minted here, never read from the client: an id a caller chooses is a way
    to write into someone else's trail. Plain ASGI rather than Starlette's
    ``BaseHTTPMiddleware`` because the bind has to span the *send*: uvicorn
    writes its access line from inside ``send`` when the response starts,
    after the endpoint has returned, and a bind that ends with the handler
    leaves exactly that line null.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        with bind_request(request_id):
            await self.app(scope, receive, send_with_id)


_HANDLER_NAME = "panelverdict-json"

# Uvicorn installs its own plain-text handlers on these when it starts, before
# it imports the app. Left alone, its access and lifecycle lines would be the
# only lines on the server that are not JSON.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging() -> None:
    """Install the JSON handler on the root logger, once.

    Not ``basicConfig``: that is a no-op when the root already has a handler,
    which under uvicorn and under pytest it does. The handler is found by name
    so the server entry point and the scripts can all call this. Uvicorn's own
    handlers are dropped, so a ``--log-config`` given to it would be too.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(handler.get_name() == _HANDLER_NAME for handler in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(_HANDLER_NAME)
        handler.addFilter(ContextStamp())
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    for name in UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
