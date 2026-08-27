"""Nothing blocking may run on the event loop.

111/#240 converted the request path, and the review found the conversion had
missed three blocking calls and a whole module. The cause is structural rather
than careless: `Screener`, `Embedder`, `RolePlayGenerator` and
`TargetTranslator` are *sync* protocols, and `psycopg.Connection` is a sync
type, so every async caller has to independently remember `asyncio.to_thread`.
Four sites remembered and three forgot, and neither the type checker nor 717
tests noticed.

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
    "deny_data_api",  # DDL on a sync connection
    "collect_panel_votes",  # the ThreadPoolExecutor over model calls
    "psycopg.connect",  # a sync connection, TLS handshake and all
    "_fetch_personas",  # the sync twin of `_afetch_personas`
    "verifier.subject",  # a blocking JWKS fetch (app/auth.py)
    "remaining_credit",  # a live OpenRouter GET
    "_sweep_data_api",  # sync by design; the lifespan must thread it
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
        # What `asyncio.to_thread` was handed is exactly what is allowed. Keyed
        # on identity: the argument node is the same object the call check sees.
        excused = {
            id(node.args[0])
            for node in body
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
            and node.args
        }
        for node in body:
            if not isinstance(node, ast.Call) or id(node) in excused:
                continue
            spelling = _spelling(node.func)
            if spelling in BLOCKING:
                found.append(f"{path}:{node.lineno} {fn.name} -> {spelling}()")
    return found


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
