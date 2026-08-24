import hmac
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import NamedTuple

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.analyst import ToolDeps, analysis_facts, stream_analyst
from app.assembly import Embedder
from app.config import USD_PER_VOTE, settings
from app.db import check_connection
from app.llm import (
    OpenRouterEmbedder,
    OpenRouterPanelLLM,
    OpenRouterTargetTranslator,
    analyst_chat_model,
    remaining_credit,
)
from app.panel import votes_with_voters
from app.pipeline import EmptyPanel, NoVotes, run_panel_test
from app.schemas import (
    ChatRequest,
    EvaluateRequest,
    EvaluateResponse,
    Notice,
)
from app.screening import OpenRouterScreener, Screener, UnsafeInput, screen_inputs
from app.targeting import TargetTranslator
from app.vote import OutOfCredit, PanelLLM

# Uvicorn configures its own loggers and leaves the root one alone, so every
# `logger.info` in this package propagated to a handler-less root and was
# dropped at WARNING. The effect was that a run's usage line — what it cost,
# and how long it took — has never been readable from a running
# server, only from tests, which capture at the logger and so could not see the
# gap. Configured here because this module is the server's entry point; the
# seed script does the same for the same reason.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The app's only startup/shutdown lifecycle: the analyst's checkpointer.

    One saver for the process lifetime — threads must outlive requests, which
    is the whole point of a checkpointer. In Postgres (#144) so a restart or a
    second worker resumes the same transcript; the in-memory saver made a
    resumed thread silently start from nothing, and an analyst with no memory
    of its own words can contradict the answer on screen. The saver cannot
    borrow `get_conn`: that connection is request-lifetime by contract, this
    one is startup-to-shutdown.

    A pool of exactly one connection, both halves on purpose:
    - one, because PostgresSaver serializes every operation behind a process
      lock (its `_cursor` takes `self.lock`), so a second connection could
      never be used;
    - a pool rather than a bare Connection, because `check=` on checkout
      replaces a connection the Supabase pooler has dropped during an idle
      spell, where a bare Connection would stay broken until the next deploy.
    The connection kwargs mirror `PostgresSaver.from_conn_string`'s own.

    `setup()` runs here, not in schema.sql or the seed: the checkpoint tables
    are the library's, versioned by its own `checkpoint_migrations` table, so
    a library upgrade must be able to migrate them at deploy time without a
    reseed. Project tables remain the seed's job (see `get_conn`). DDL through
    the session pooler (port 5432) is fine — 006f's rule bans only the
    transaction pooler.
    """
    with ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=1,
        check=ConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        app.state.checkpointer = checkpointer
        yield


app = FastAPI(title="PanelVerdict API", lifespan=lifespan)

# The two endpoints that spend money (045/#143). CORS below is a browser
# courtesy that curl ignores; this middleware is the actual gate, and it runs
# before any dependency does work — a refused request costs nothing, the same
# property 013 established for refused content. Timing-safe comparison because
# the whole point of the secret is an attacker guessing it.
_PAID_PATHS = ("/evaluate", "/chat")


@app.middleware("http")
async def require_shared_secret(request: Request, call_next):
    secret = settings.api_shared_secret
    if secret is not None and request.url.path in _PAID_PATHS:
        # Compared as bytes: Starlette hands header values back latin-1
        # decoded, and `compare_digest` raises TypeError on a str holding a
        # non-ASCII codepoint — so `x-api-key: café` used to become a 500 with
        # a traceback instead of a plain refusal.
        offered = request.headers.get("x-api-key", "").encode("latin-1")
        if not hmac.compare_digest(offered, secret.get_secret_value().encode()):
            return JSONResponse(
                status_code=401,
                content={"detail": "missing or wrong API secret"},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _require_api_key() -> str:
    key = settings.openrouter_api_key
    if key is None:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY is not set")
    return key.get_secret_value()


def get_panel_llm() -> PanelLLM:
    return OpenRouterPanelLLM(
        api_key=_require_api_key(),
        base_url=settings.openrouter_base_url,
        provider=settings.model_provider,
        model=settings.panel.model,
    )


def get_screener() -> Screener | None:
    """None when no key is configured, because screening is advisory and a
    missing key already means "advisory checks do not run" rather than "the
    product is down" — the same reading the credit pre-flight takes."""
    key = settings.openrouter_api_key
    if key is None:
        return None
    return OpenRouterScreener(
        api_key=key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        provider=settings.model_provider,
        model=settings.screening_model,
    )


def get_translator() -> TargetTranslator:
    """Translate target description into structured output for the panel"""
    return OpenRouterTargetTranslator(
        api_key=_require_api_key(),
        base_url=settings.openrouter_base_url,
        provider=settings.model_provider,
        model=settings.targeting_model,
    )


def get_embedder() -> Embedder:
    """The query half of search_personas — same model that embedded the pool,
    so query and corpus vectors live in one space."""
    return OpenRouterEmbedder(
        api_key=_require_api_key(),
        base_url=settings.openrouter_base_url,
        provider=settings.model_provider,
        model=settings.embedding_model,
    )


def get_analyst() -> BaseChatModel:
    return analyst_chat_model(
        api_key=_require_api_key(),
        base_url=settings.openrouter_base_url,
        provider=settings.model_provider,
        model=settings.analyst_model,
    )


def get_remaining_credit() -> float | None:
    if settings.openrouter_api_key is None:
        return None
    return remaining_credit(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
    )


def budget_notice(remaining: float | None, *, size: int) -> tuple[Notice, ...]:
    """Warn-and-proceed, never refuse: a run the credit cannot
    finish is still worth starting, because every vote it casts lands in the ledger
    and a re-run after top-up resumes free. None never warns — an unknown balance
    is an unlimited key or a failed check, not evidence of a thin one."""
    if remaining is None:
        return ()
    estimated = size * USD_PER_VOTE
    if remaining >= estimated:
        return ()
    return (
        Notice(
            severity="warning",
            message=(
                f"Your OpenRouter credit (${remaining:.2f}) may not cover this run "
                f"(about ${estimated:.2f}). The run proceeds anyway: votes already "
                "cast are saved, so topping up and re-running resumes at no extra "
                "cost."
            ),
        ),
    )


def get_conn() -> Iterator[psycopg.Connection]:
    """One plain connection per request, pgvector adapter registered.

    The adapter is per-connection state and the chat path binds query vectors
    (search_personas), so every checkout gets it. Deliberately NOT
    `prepare_connection`: that also runs schema DDL, which is the seed's job,
    not a request's.
    """
    with psycopg.connect(settings.database_url) as conn:
        register_vector(conn)
        yield conn


class _Charge(NamedTuple):
    """One cap to enforce: how many rows this key may hold in the window."""

    endpoint: str
    key: str
    limit: int
    unit: str


def caller_id(request: Request) -> str:
    """Who to count, from the one header a visitor cannot choose.

    X-Client-Id is set by our proxy, which overwrites whatever the caller sent
    using a value its platform supplies — and the proxy is trustworthy here
    precisely because the shared secret the middleware just checked proves the
    request came from it. Deliberately NOT X-Forwarded-For: platforms append
    rather than replace, so its leftmost entry is caller-written text, and
    keying a rate limit on it let anyone mint unlimited budgets by varying one
    header. Falling back to the socket peer keeps a direct call (which still
    needs the secret) counted rather than uncounted.
    """
    asserted = request.headers.get("x-client-id", "").strip()
    if asserted:
        return asserted
    return request.client.host if request.client else "unknown"


def enforce_run_limit(
    request: EvaluateRequest,
    caller: str = Depends(caller_id),
    conn: psycopg.Connection = Depends(get_conn),
) -> None:
    """Postgres-backed runs-per-day gate on the paid run (045/#143).

    Declares the body it never reads, and that is the point: dependencies
    resolve before the endpoint's own body is validated, so without this a
    payload the schema rejects would spend one of the caller's runs on its way
    to a 422. Validating here puts the free refusal first, keeping 013's rule
    that a refused request costs nothing. Same name as the handler's parameter,
    or FastAPI would treat the two as separate embedded body fields.

    The count lives in Postgres for the same reason the checkpointer does
    (#144) — a redeploy or a second worker must not forget it. Refusal costs
    nothing: this raises before the handler and its model calls run. The
    attempt is recorded before the run so a caller cannot probe for free, and
    the write sweeps the caller's expired rows so the ledger cannot accumulate
    rows nobody will read again (040's lesson).
    """
    _charge_ledger(
        conn,
        _Charge("/evaluate", caller, settings.evaluate_runs_per_day, "runs"),
    )


def enforce_turn_limit(
    request: ChatRequest,
    caller: str = Depends(caller_id),
    conn: psycopg.Connection = Depends(get_conn),
) -> None:
    """Two counts, because each bounds a different runaway (045/#143).

    Per thread, since a request is not the unit of /chat's cost — a turn is,
    and turns accumulate in a thread. Per caller as well, because the *client*
    mints thread ids: a thread-only cap is one the abuser resets by sending a
    new id, so it would bound the honest conversation and nothing else. The
    refusal must land before there is a stream to be unable to refuse.
    Declaring the body model here shares FastAPI's single parse with the
    handler.
    """
    _charge_ledger(
        conn,
        _Charge(
            "/chat",
            request.thread_id,
            settings.chat_turns_per_thread_per_day,
            "turns for this thread",
        ),
        _Charge(
            "/chat-caller", caller, settings.chat_turns_per_caller_per_day, "turns"
        ),
    )


def _charge_ledger(conn: psycopg.Connection, *charges: _Charge) -> None:
    """Enforce every cap, then record one attempt against each — or refuse.

    Count-then-insert is not a limit under load: READ COMMITTED cannot see
    another transaction's uncommitted rows and sync handlers run in a thread
    pool, so simultaneous requests all read the same `used` and all pass — 10
    concurrent requests took 7 slots out of a limit of 3, measured. A per-key
    advisory lock makes the database arbitrate; it is held to the end of this
    transaction and taken in a stable order so two callers charging the same
    pair of keys cannot deadlock.

    All caps are checked before any is recorded, so a request refused by one
    cap does not silently consume another's budget. `limit <= 0` disables a cap
    outright — the escape hatch for local iteration.

    The write sweeps the key's expired rows, so the ledger never accumulates
    rows nobody will read again (040's lesson).
    """
    active = [charge for charge in charges if charge.limit > 0]
    if not active:
        return
    window = "requested_at > now() - interval '24 hours'"
    with conn.cursor() as cur:
        for charge in sorted(active):
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"{charge.endpoint}:{charge.key}",),
            )
        for charge in active:
            cur.execute(
                "DELETE FROM request_ledger WHERE endpoint = %s AND caller = %s"
                " AND requested_at < now() - interval '24 hours'",
                (charge.endpoint, charge.key),
            )
            cur.execute(
                "SELECT count(*) FROM request_ledger"
                f" WHERE endpoint = %s AND caller = %s AND {window}",
                (charge.endpoint, charge.key),
            )
            row = cur.fetchone()
            if (int(row[0]) if row else 0) >= charge.limit:
                # Release the locks now rather than at request teardown; the
                # discarded sweep is opportunistic and costs nothing.
                conn.rollback()
                # The sentence is this codebase's own and names the remedy; the
                # counted identity never travels back.
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"limit reached ({charge.limit} {charge.unit} per day)"
                        " — try again tomorrow"
                    ),
                )
        for charge in active:
            cur.execute(
                "INSERT INTO request_ledger (endpoint, caller) VALUES (%s, %s)",
                (charge.endpoint, charge.key),
            )
    conn.commit()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db": "up" if check_connection() else "down"}


@app.post("/evaluate")
def evaluate(
    request: EvaluateRequest,
    _limit: None = Depends(enforce_run_limit),
    llm: PanelLLM = Depends(get_panel_llm),
    translator: TargetTranslator = Depends(get_translator),
    conn: psycopg.Connection = Depends(get_conn),
    credit: float | None = Depends(get_remaining_credit),
    screener: Screener | None = Depends(get_screener),
) -> EvaluateResponse:
    variants = {"a": request.headline_a, "b": request.headline_b}
    # Before the panel, because this is the last moment the customer's text has
    # been copied only once — and before a single vote is bought, so a refused
    # run costs nothing.
    try:
        screen_inputs(screener, [request.target_description, *variants.values()])
    except UnsafeInput as error:
        # 400 and not 422: the text is well-formed, it is what it says that was
        # refused. The sentence is this codebase's own and names the remedy;
        # the screener's own words never travel.
        raise HTTPException(status_code=400, detail=str(error)) from error
    # Both refusal messages are safe to forward by construction: `EmptyPanel` is this
    # codebase's own sentence, and `NoVotes` carries exception types only — never the
    # failure text, which can include provider responses and the model's own output.
    try:
        result = run_panel_test(
            conn,
            description=request.target_description,
            variants=variants,
            size=settings.panel.size,
            translator=translator,
            llm=llm,
        )
    except EmptyPanel as error:
        # The request is the problem — the target names an audience this pool cannot
        # serve — so the code says "fix what you asked", not "the service failed".
        raise HTTPException(status_code=422, detail=str(error)) from error
    except NoVotes as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except OutOfCredit as error:
        # The account's fault, not the server's, and the remedy is in the message:
        # the text is this codebase's own sentence, never the provider's.
        raise HTTPException(status_code=402, detail=str(error)) from error
    return EvaluateResponse(
        verdict=result.verdict,
        tally=result.tally,
        counts=result.counts,
        query=result.selection.query,
        notices=budget_notice(credit, size=settings.panel.size) + result.notices,
        stop_reason=result.stop_reason,
        variants=variants,
        votes=votes_with_voters(result.votes.records, result.selection.panel),
    )


def get_checkpointer(request: Request) -> BaseCheckpointSaver:
    """The lifespan's process-lifetime saver, exposed as a dependency so tests
    can swap in an InMemorySaver — thread durability is test_analyst's
    subject, not a tax on every endpoint test."""
    return request.app.state.checkpointer


@app.post("/chat")
def chat(
    request: ChatRequest,
    _limit: None = Depends(enforce_turn_limit),
    analyst: BaseChatModel = Depends(get_analyst),
    conn: psycopg.Connection = Depends(get_conn),
    embedder: Embedder = Depends(get_embedder),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
) -> StreamingResponse:
    # No translator and no panel model: with `run_panel_test` gone, this
    # endpoint has nothing that could buy a vote. The absence is the guarantee —
    # a spend path cannot be reintroduced here without a visible new dependency.
    # Validated before the stream starts, so a malformed tally costs a 422 and
    # no model call — this is the last moment a status code can still say it.
    # Every later failure is the stream's to report, as an in-band `error`
    # event with a fixed sentence (see stream_analyst).
    try:
        analysis_facts(request.result)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return StreamingResponse(
        stream_analyst(
            model=analyst,
            result=request.result,
            thread_id=request.thread_id,
            message=request.message,
            checkpointer=checkpointer,
            deps=ToolDeps(conn=conn, embedder=embedder),
        ),
        media_type="application/x-ndjson",
    )
