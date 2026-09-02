"""047/#145: every log line is one JSON object carrying a timestamp and the ids
that place it — the request it served and the run (thread) it belongs to."""

import json
import logging
import pytest
from datetime import UTC, datetime

from app.logs import JsonFormatter


def _record(
    message: str, *args, level: int = logging.INFO, **extra
) -> logging.LogRecord:
    record = logging.getLogger("app.somewhere").makeRecord(
        "app.somewhere", level, "somewhere.py", 12, message, args, None, extra=extra
    )
    return record


def test_a_line_is_one_json_object_with_a_timestamp() -> None:
    record = _record("panel usage test_id=%s", "abc")

    line = JsonFormatter().format(record)

    assert "\n" not in line
    event = json.loads(line)
    assert event["message"] == "panel usage test_id=abc"
    assert event["level"] == "INFO"
    assert event["logger"] == "app.somewhere"
    # An aggregator can place the line: an ISO-8601 instant in UTC, to the
    # millisecond, equal to when the record was made.
    stamped = datetime.fromisoformat(event["time"])
    assert stamped.tzinfo is not None
    assert (
        abs(stamped - datetime.fromtimestamp(record.created, UTC)).total_seconds()
        < 0.001
    )


def test_extra_fields_are_top_level_keys_not_text() -> None:
    record = _record("panel usage", test_id="t-1", wall_seconds=12.5, input_tokens=800)

    event = json.loads(JsonFormatter().format(record))

    # "which runs cost more than X" is a query on a field, not a regex on a repr.
    assert event["test_id"] == "t-1"
    assert event["wall_seconds"] == 12.5
    assert event["input_tokens"] == 800
    # The record's own plumbing does not leak into the line.
    assert not {"args", "msg", "levelno", "pathname", "created", "msecs"} & set(event)


def test_an_exception_travels_on_the_same_line() -> None:
    try:
        raise RuntimeError("the report was not kept")
    except RuntimeError:
        record = logging.getLogger("app.somewhere").makeRecord(
            "app.somewhere",
            logging.ERROR,
            "x.py",
            1,
            "could not keep the report",
            (),
            __import__("sys").exc_info(),
        )

    line = JsonFormatter().format(record)

    assert "\n" not in line
    event = json.loads(line)
    assert event["message"] == "could not keep the report"
    assert "RuntimeError: the report was not kept" in event["exception"]
    assert "Traceback" in event["exception"]


def test_bound_ids_are_stamped_on_every_record_and_unbound_after() -> None:
    from app.logs import ContextStamp, bind_request, bind_thread

    stamp = ContextStamp()
    formatter = JsonFormatter()

    with bind_request("req-1"), bind_thread("thread-1"):
        inside = _record("screening blocked input")
        stamp.filter(inside)
    outside = _record("evaluate")
    stamp.filter(outside)

    within = json.loads(formatter.format(inside))
    assert within["request_id"] == "req-1"
    assert within["thread_id"] == "thread-1"
    # A refused request has no run: the keys are there to query on, and null.
    after = json.loads(formatter.format(outside))
    assert after["request_id"] is None
    assert after["thread_id"] is None
    # The stamp never drops a record.
    assert stamp.filter(inside) is True


@pytest.fixture
def root_restored():
    root = logging.getLogger()
    before = (list(root.handlers), root.level)
    uvicorn_before = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).propagate,
        )
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
    }
    yield root
    root.handlers[:], root.level = before[0], before[1]
    root.setLevel(before[1])
    for name, (handlers, propagate) in uvicorn_before.items():
        logging.getLogger(name).handlers[:] = handlers
        logging.getLogger(name).propagate = propagate


def test_configure_installs_one_json_handler_and_routes_uvicorn_through_it(
    root_restored,
) -> None:
    from app.logs import ContextStamp, configure_logging

    # Uvicorn configures these before the app is imported, with its own
    # plain-text handlers; a line that bypasses ours is not JSON.
    logging.getLogger("uvicorn.access").addHandler(logging.NullHandler())
    logging.getLogger("uvicorn.access").propagate = False

    configure_logging()
    configure_logging()  # a second call (main and seed both configure) adds nothing

    ours = [h for h in root_restored.handlers if isinstance(h.formatter, JsonFormatter)]
    assert len(ours) == 1
    assert any(isinstance(f, ContextStamp) for f in ours[0].filters)
    assert root_restored.level == logging.INFO
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate is True


def test_an_explicit_thread_id_field_wins_over_the_bound_one() -> None:
    """A line logged outside the bind — the analyst's usage line, written while
    the response is still streaming — names its own thread; the stamp must not
    null it."""
    from app.logs import ContextStamp, bind_thread

    record = _record("analyst usage", thread_id="chat-7")
    with bind_thread("other"):
        ContextStamp().filter(record)

    assert record.thread_id == "chat-7"


@pytest.mark.anyio
async def test_the_bind_spans_the_response_send_so_the_access_line_has_the_id(
    caplog,
) -> None:
    """Uvicorn writes its access line from inside `send`, when the response
    starts — after an endpoint has returned. A bind that ends with the handler
    leaves exactly that line null."""
    from app.logs import ContextStamp, RequestIdMiddleware

    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    started: list[dict] = []

    async def server_send(message):
        if message["type"] == "http.response.start":
            started.append(message)
            logging.getLogger("uvicorn.access").info("GET /health 200")

    caplog.handler.addFilter(ContextStamp())
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        await RequestIdMiddleware(endpoint)(
            {"type": "http", "headers": []}, None, server_send
        )

    (record,) = caplog.records
    header = dict(started[0]["headers"])[b"x-request-id"].decode()
    assert len(header) == 36
    assert record.request_id == header


def test_uvicorn_s_colour_copy_of_the_message_is_not_a_field() -> None:
    record = _record(
        "Started server process [%d]", 7, color_message="Started \x1b[36m%d\x1b[0m"
    )

    event = json.loads(JsonFormatter().format(record))

    assert event["message"] == "Started server process [7]"
    assert "color_message" not in event
