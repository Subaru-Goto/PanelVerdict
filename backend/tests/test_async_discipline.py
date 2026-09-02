"""Nothing blocking may run on the event loop.

111/#240 converted the request path, and the review found the conversion had
missed three blocking calls and a whole module. The cause is structural rather
than careless: `Screener`, `Embedder`, `RolePlayGenerator` and
`TargetTranslator` are *sync* protocols, and `psycopg.Connection` is a sync
type, so every async caller has to independently remember `asyncio.to_thread`.
Four sites remembered and three forgot, and 717 tests did not notice. Nor could a
type checker have: there is none here — `ci.yml` runs `pytest` alone and the dev
group is anyio, pytest, ruff, testcontainers — so the ~30 `Connection` ->
`AsyncConnection` signature changes this conversion made are enforced by nothing
but this file and the suite. 103/#221 owns that gap.

**What this is and is not.** The file list is derived from the tree, so a module
added tomorrow is covered the day it appears. The *symbol* list below is not —
it is hand-maintained, and a blocking call it does not name passes silently.
An earlier version of this docstring called the whole rule "a measurement, not
a memory"; the review took that apart, and it was the half that decides whether
anything is found. So: a tripwire for the shapes that have actually gone wrong
here, and a place to add the next one — not a proof that the loop is clean.

Known blind spots, recorded rather than implied: a call reached through an
alias (`emb.embed`), and one made from a helper that a coroutine calls but does
not lexically contain.
"""

import ast
from pathlib import Path

from pytest import mark

APP = Path(__file__).resolve().parents[1] / "app"

# Every component whose call crosses the network synchronously, spelled the way
# a call site spells it. Methods carry their receiver: a bare `delete` also
# matches FastAPI's own `@app.delete` route decorator, which is how the first
# version of this test failed on a line that was never a problem.
BLOCKING = {
    "translator.translate",  # TargetTranslator
    "generator.draft",  # RolePlayGenerator
    "generator.check",  # RolePlayGenerator
    "screener.screen",  # Screener
    "embedder.embed",  # Embedder
    "llm.vote",  # PanelLLM
    "deleter.delete",  # AccountDeleter — synchronous httpx
    "check_connection",  # app.db — psycopg.connect with a 3s timeout
    "screen_inputs",  # app.screening, wraps Screener
    "probe_screener",  # app.screening, wraps Screener — the boot probe
    "deny_data_api",  # DDL on a sync connection; the lifespan uses the async twin
    "collect_panel_votes",  # the ThreadPoolExecutor over model calls
    "psycopg.connect",  # a sync connection, TLS handshake and all
    "_fetch_personas",  # the sync twin of `_afetch_personas`
    "verifier.subject",  # a blocking JWKS fetch (app/auth.py)
    "remaining_credit",  # a live OpenRouter GET
    # The graph and the checkpointer, whose sync and async halves differ by one
    # letter — and whose sync half on an async path is the bug this file was
    # written after. `setup` is deliberately absent: `AsyncPostgresSaver.setup`
    # is a coroutine, so naming it would flag the lifespan's own `await`.
    "graph.invoke",
    "graph.stream",
    "graph.get_state",
    "graph.update_state",
    "checkpointer.get",
    "checkpointer.get_tuple",
    "checkpointer.put",
    "checkpointer.put_writes",
    "checkpointer.list",
    # Every public entry point that takes a sync `psycopg.Connection`. These were
    # absent, and `app/pool_overview.py` already calls `load_pool` — so a
    # `GET /pool` written as `async def` would have put a full-table read on the
    # loop with this gate green. Derived from the signatures, not recalled:
    # `grep -n "conn: psycopg.Connection" app/`.
    "apply_schema",
    "prepare_connection",
    "persist_pool",
    "load_pool",
    "load_persona_sample",
    "seed_corpus",
    "register_vector",  # the sync twin of register_vector_async
}

# Where a blocking call is allowed to appear inside an async function.
THREADED = "asyncio.to_thread"


def _spelling(func: ast.AST) -> str | None:
    """How the call is written: `embed` for a plain name, `embedder.embed` for
    a method — the last two segments, so `deps.embedder.embed` still matches."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        receiver = func.value
        if isinstance(receiver, ast.Name):
            return f"{receiver.id}.{func.attr}"
        if isinstance(receiver, ast.Attribute):
            return f"{receiver.attr}.{func.attr}"
        return func.attr
    return None


def _own_body(fn: ast.AST) -> list[ast.AST]:
    """Every node lexically inside `fn` but not inside a function nested in it.

    Without this the gate charged a coroutine for a call in a nested plain
    `def` — which never touches the loop, and is the natural shape of a
    callable handed to `to_thread`, so the rule failed on the pattern it exists
    to encourage. It also reported a nested `async def`'s single offence once
    per enclosing scope.
    """
    own: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        own.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return own


def _offences(tree: ast.AST, path: str) -> list[str]:
    found: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        body = _own_body(fn)
        # Nothing is excused, and that is the rule rather than a simplification.
        # What `to_thread` is handed is a *reference* — `deleter.delete`, not
        # `deleter.delete(...)` — so it is not a call and there is nothing here to
        # exempt. A call written in that position would be evaluated before
        # `to_thread` ever ran, i.e. on the loop, so exempting it would hide the
        # offence rather than allow a safe one. An earlier version tried, keyed on
        # node identity, and matched nothing at all.
        for node in body:
            if not isinstance(node, ast.Call):
                continue
            spelling = _spelling(node.func)
            if spelling in BLOCKING:
                found.append(f"{path}:{node.lineno} {fn.name} -> {spelling}()")
    return found


class TestTheGateItself:
    """The gate has been wrong twice — once flagging a line that was never a
    problem, once passing a real one for an unrelated reason. Its logic is
    checked against source it is handed, not only against `app/`."""

    def test_a_blocking_call_inside_a_coroutine_is_found(self) -> None:
        tree = ast.parse(
            "async def answer(graph, config):\n    return graph.get_state(config)\n"
        )

        assert _offences(tree, "x.py")

    def test_a_reference_handed_to_a_thread_is_not_a_call(self) -> None:
        """`asyncio.to_thread(deleter.delete, caller)` passes the method, it does
        not call it — the shape the rule exists to encourage."""
        tree = ast.parse(
            "async def forget(deleter, caller):\n"
            "    await asyncio.to_thread(deleter.delete, caller)\n"
        )

        assert _offences(tree, "x.py") == []

    def test_a_sync_database_entry_point_is_found(self) -> None:
        """The class of call the list had been missing entirely: a public helper
        taking a sync `psycopg.Connection`, called straight from a coroutine."""
        tree = ast.parse("async def overview(conn):\n    return load_pool(conn)\n")

        assert _offences(tree, "x.py")

    def test_an_argument_to_a_thread_is_still_evaluated_on_the_loop(self) -> None:
        """Why the gate excuses nothing.

        It used to exempt `to_thread`'s first argument, keyed on the node's
        identity. That was dead — the argument is a *reference*, never a `Call`,
        so it could not match what the check looks at — and had it ever matched
        it would have hidden a genuine offence: an argument is evaluated before
        `to_thread` is called, so a call written there blocks the loop exactly as
        if the wrapper were not there.
        """
        tree = ast.parse(
            "async def boot():\n    await asyncio.to_thread(check_connection())\n"
        )

        assert _offences(tree, "x.py")


SOURCES = sorted(APP.rglob("*.py"))


def test_the_gate_is_looking_at_something() -> None:
    """An empty `parametrize` list is a skip, not a failure — so renaming or
    moving `app/` would turn every case below silently green."""
    assert len(SOURCES) > 10


@mark.parametrize("source", SOURCES, ids=lambda p: p.name)
def test_no_blocking_call_runs_on_the_event_loop(source: Path) -> None:
    tree = ast.parse(source.read_text())
    offences = _offences(tree, source.name)
    assert offences == [], (
        f"blocking calls inside `async def` — wrap each in `{THREADED}`:\n"
        + "\n".join(offences)
    )
