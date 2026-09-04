import asyncio
from concurrent.futures import ThreadPoolExecutor
import base64
import hmac
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, NamedTuple
from uuid import uuid4

import anyio
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from starlette.types import Receive, Scope, Send

from app.analyst import ToolDeps, stream_analyst
from app.assembly import Embedder
from app.auth import (
    AccountDeleter,
    DeletionFailed,
    InvalidSession,
    SessionUnverifiable,
    SupabaseVerifier,
    bearer_token,
    deleter_from_settings,
    verifier_from_settings,
)
from app.config import (
    USD_PER_ROLEPLAY,
    USD_PER_TURN,
    USD_PER_VOTE,
    settings,
)
from app.db import CONNECT_TIMEOUT_SECONDS, check_connection
from app.demo import DEMO_CASES, ReplayPanel, UnreachableGenerator, load_fixture
from app.graph import GateDecision, PanelPreview, build_evaluate_graph
from app.chat_guard import (
    BlockedMessage,
    ChatGuard,
    ContentRefused,
    MistralChatGuard,
    guard_chat_message,
    probe_chat_guard,
)
from app.llm import (
    OpenRouterEmbedder,
    OpenRouterPanelLLM,
    OpenRouterRolePlayGenerator,
    analyst_chat_model,
    remaining_credit,
)
from app.logs import RequestIdMiddleware, bind_thread, configure_logging
from app.panel import render_persona_prompt, votes_with_voters
from app.persistence import (
    adeny_data_api,
    count_reports,
    delete_report,
    delete_reports_of,
    list_reports,
    load_personas_by_id,
    load_report,
    store_report,
    sweep_unkept_reports,
)
from app.pipeline import EmptyPanel, NoVotes
from app.roleplay import GeneratorFault, RolePlayGenerator, RolePlayRefused
from app.schemas import (
    ChatRequest,
    EvaluateRequest,
    EvaluateResponse,
    Notice,
    PanelEdit,
    PanelVerdict,
    ResumeRequest,
    RunTimings,
    RunUsage,
    TargetQuery,
    VoteTally,
)
from app.screening import (
    OpenRouterScreener,
    Screener,
    UnsafeInput,
    probe_screener,
    self_model_name,
)
from app.targeting import CROSS_SECTION_NOTICE, settled_query
from app.tracing import configure_tracing
from app.vote import OutOfCredit, PanelLLM, total_usage

# Uvicorn configures its own loggers and leaves the root one alone, so every
# `logger.info` in this package propagated to a handler-less root and was
# dropped at WARNING. The effect was that a run's usage line — what it cost,
# and how long it took — has never been readable from a running
# server, only from tests, which capture at the logger and so could not see the
# gap. Configured here because this module is the server's entry point; the
# seed script does the same for the same reason. JSON lines with the request
# and thread ids since 047/#145 (`app/logs.py`).
configure_logging()

logger = logging.getLogger(__name__)

# At import, before the first model client exists: `init_chat_model` reads the
# tracing environment when it builds a client.
_TRACING = configure_tracing()
if _TRACING:
    # The project, never the key. A deploy that sends reader input off our
    # infrastructure should say so in its own logs.
    logger.info(
        "langsmith tracing is on: project=%s endpoint=%s",
        settings.langsmith_project,
        settings.langsmith_endpoint,
    )
elif settings.langsmith_tracing:
    # This deployment believes it is tracing and nothing else would say
    # otherwise.
    logger.warning(
        "LANGSMITH_TRACING is set but LANGSMITH_API_KEY is not: tracing stays off"
    )


async def _enforce_screener_policy() -> None:
    """Boot policy for the screener probe (072/#163): announce everywhere,
    refuse where SCREENER_REQUIRED says this deployment must have its control.

    Runs before the boot takes the pooler slot it may be about to refuse. One
    real classifier call per process — the failure that actually happened here
    was 404 on this account, which a free model-list check cannot see. The
    off/outage classification is `probe_screener`'s; an outage never refuses,
    required or not, and the WARNING-versus-ERROR level below is that same
    distinction. This asserts the control at the boot instant only: a mid-life
    revocation still fails open per request, one ERROR line each, until the
    next boot.
    """
    screener = get_screener()
    if screener is None:
        if settings.screener_required:
            raise RuntimeError(
                "SCREENER_REQUIRED is set but OPENROUTER_API_KEY is not: the"
                " screener cannot run, so this deployment refuses to start"
            )
        return
    outcome = await asyncio.to_thread(probe_screener, screener)
    if outcome == "off":
        if settings.screener_required:
            raise RuntimeError(
                "SCREENER_REQUIRED is set and the screening model is not"
                " available to this account (the control is off, not"
                f" degraded): model={self_model_name(screener)}"
            )
        logger.error(
            "the screening model is not available to this account — the"
            " control is off, not degraded: model=%s",
            self_model_name(screener),
        )
    elif outcome == "outage":
        logger.warning(
            "the screener did not answer the startup probe (outage, not"
            " configuration): model=%s — requests fail open until it heals",
            self_model_name(screener),
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """The app's only startup/shutdown lifecycle: the shared executor's size,
    the screener probe, then the analyst's checkpointer.

    One saver for the process lifetime — threads must outlive requests, which
    is the whole point of a checkpointer. In Postgres (#144) so a restart or a
    second worker resumes the same transcript; the in-memory saver made a
    resumed thread silently start from nothing, and an analyst with no memory
    of its own words can contradict the answer on screen. The saver cannot
    borrow `get_conn`: that connection is request-lifetime by contract, this
    one is startup-to-shutdown.

    A pool of exactly one connection, both halves on purpose:
    - one, because AsyncPostgresSaver serializes every operation behind a
      process-wide lock (its `_cursor` takes `async with self.lock`), so a
      second connection could never be used;
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
    # The loop's default executor carries every to_thread, every sync graph
    # node and every new connection's DNS lookup. Python sizes it to cpu+4 —
    # five on a 1-vCPU container by that rule, or whatever core count a shared
    # host reports. It fronts `pooler_pool_size` connections,
    # so it gets that many workers (112/#242); threads waiting on the network
    # are cheap, and the pool, not the CPU count, is the ceiling that means
    # something here. Set before anything below uses it.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(
            max_workers=settings.pooler_pool_size, thread_name_prefix="shared"
        )
    )
    await _enforce_screener_policy()
    global _chat_guard
    _chat_guard = _build_chat_guard()
    await _enforce_chat_guard_policy(_chat_guard)
    # The type names the row shape the saver expects; `row_factory` below is
    # what actually produces it.
    async with AsyncConnectionPool[AsyncConnection[DictRow]](
        settings.database_url,
        min_size=1,
        max_size=1,
        check=AsyncConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    ) as pool:
        await pool.open(wait=True)
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        # After setup(), not before: the sweep must reach the tables the
        # library just created, which hold analyst transcripts and would
        # otherwise sit readable over the project's Data API — a surface this
        # release opens by shipping a publishable key to the browser
        # (063/#158). `test_the_lifespan_closes_every_table_to_the_data_api`
        # asserts both halves against the database, ordering included.
        #
        # Through the pool's own connection, as the sync version did. A separate
        # `psycopg.connect` here cost a second pooler slot at boot and needed a
        # connect deadline nobody has measured for a cold pooler — a bounded
        # failure invented to replace an unbounded wait that could not happen,
        # since a borrowed connection performs no connect.
        async with pool.connection() as swept:
            await adeny_data_api(swept)
        app.state.checkpointer = checkpointer
        if settings.api_shared_secret is not None and _VERIFIER is None:
            # A shared secret set is this deployment saying it is not a laptop.
            # Sign-in unconfigured alongside it is almost always a missing
            # variable rather than a decision, and the symptom — every quota
            # quietly counting an address again — is invisible from outside.
            logger.warning(
                "sign-in is not configured (SUPABASE_PROJECT_URL unset): run"
                " limits count a forwarded address, not an account"
            )
        try:
            yield
        finally:
            if _chat_guard is not None:
                await _chat_guard.aclose()


app = FastAPI(title="PanelVerdict API", lifespan=lifespan)

# The endpoints that must have come from our own proxy (045/#143). CORS below
# is a browser courtesy that curl ignores; this middleware is the actual gate,
# and it runs before any dependency does work — a refused request costs
# nothing, the same property 013 established for refused content. Timing-safe
# comparison because the whole point of the secret is an attacker guessing it.
#
# /evaluate and /chat are here because they spend money. /me is here because it
# erases an account (063/#158): it costs nothing, but it is the one irreversible
# thing a caller can ask for, and a stolen session token should get no further
# against it than against a paid run. Its GET rides along — no reason to open a
# door for the half that only reads.
#
# /tests is here for both of those reasons at once (117/#252). `DELETE
# /tests/{id}` is the second irreversible thing, and the reads hand back the
# customer's own content — their headline text, and the phrases their audience
# reading was quoted from. It matters more here than on a paid path: with
# `supabase_project_url` unset, a state deploy.md documents as supported,
# `caller_id` falls back to a caller-written header, so without this guard the
# owner of a stored report would be whatever a request claimed it was.
#
# /demo is deliberately absent (061/#156): it spends nothing, serves the same
# replayed reports to everyone, and the states screen promises it stays
# readable when budgets are spent — a guard here would break that promise.
_GUARDED_PATHS = ("/evaluate", "/chat", "/me", "/tests")


def _is_guarded(path: str) -> bool:
    """Match a guarded route or anything under it.

    Exact membership let `/evaluate/resume` — the call that actually buys the
    votes — past the guard while `/evaluate` sat behind it.
    """
    return path in _GUARDED_PATHS or any(
        path.startswith(f"{guarded}/") for guarded in _GUARDED_PATHS
    )


@app.middleware("http")
async def require_shared_secret(request: Request, call_next):
    secret = settings.api_shared_secret
    if secret is not None and _is_guarded(request.url.path):
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


# Added after the secret check so it wraps it: a 401 is logged under a request
# id too (047/#145).
app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    # Readable from the browser, so a page can show the id an error's lines
    # are filed under.
    expose_headers=["X-Request-ID"],
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
        model=settings.screening_model,
    )


_chat_guard: MistralChatGuard | None = None


def get_chat_guard() -> ChatGuard | None:
    """The process's one guard, built at boot so its connection is reused —
    a per-request client would add a TLS handshake to every message. None
    when no Mistral key is configured: no pre-flight, same reading as
    `get_screener`."""
    return _chat_guard


def _build_chat_guard() -> MistralChatGuard | None:
    key = settings.mistral_api_key
    if key is None:
        return None
    return MistralChatGuard(
        api_key=key.get_secret_value(),
        base_url=settings.mistral_base_url,
        model=settings.moderation_model,
    )


async def _enforce_chat_guard_policy(guard: ChatGuard | None) -> None:
    """The screener's boot policy, applied to the chat pre-flight: announce
    everywhere, refuse where SCREENER_REQUIRED says this deployment must
    have its controls. One real call per process."""
    if guard is None:
        if settings.screener_required:
            raise RuntimeError(
                "SCREENER_REQUIRED is set but MISTRAL_API_KEY is not: the chat"
                " pre-flight cannot run, so this deployment refuses to start"
            )
        return
    outcome = await probe_chat_guard(guard, content=settings.chat_content_categories)
    if outcome == "off":
        if settings.screener_required:
            raise RuntimeError(
                "SCREENER_REQUIRED is set and the moderation model is not"
                " available to this account, or does not name a configured"
                f" content category: model={guard.model_name}"
            )
        logger.error(
            "the moderation model is not available to this account, or does not"
            " name a configured content category — the chat pre-flight is off,"
            " not degraded: model=%s",
            guard.model_name,
        )
    elif outcome == "outage":
        logger.warning(
            "the chat pre-flight did not answer the startup probe (outage, not"
            " configuration): model=%s — messages pass unscreened until it heals",
            guard.model_name,
        )


def get_generator() -> RolePlayGenerator:
    """The translator's new job: audience words into one panelist instruction.

    Required, not advisory like the screener. It is this channel's only gate —
    the copy screener is the wrong instrument for it — so a run without one would
    put unclassified text into a panelist's identity.
    """
    return OpenRouterRolePlayGenerator(
        api_key=_require_api_key(),
        base_url=settings.openrouter_base_url,
        model=settings.targeting_model,
    )


def get_embedder() -> Embedder:
    """The query half of search_personas — same model that embedded the pool,
    so query and corpus vectors live in one space."""
    return OpenRouterEmbedder(
        api_key=_require_api_key(),
        base_url=settings.openrouter_base_url,
        model=settings.embedding_model,
    )


def get_analyst() -> BaseChatModel:
    return analyst_chat_model(
        api_key=_require_api_key(),
        base_url=settings.openrouter_base_url,
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


DB_BUSY = "The database is busy right now. Try again in a moment."


async def get_conn() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    """One plain connection per request, pgvector adapter registered.

    The adapter is per-connection state and the chat path binds query vectors
    (search_personas), so every checkout gets it. Deliberately NOT
    `prepare_connection`: that also runs schema DDL, which is the seed's job,
    not a request's.

    **Not pooled, and that is a decision rather than an omission.** A pool was
    tried here (111/#240) to restore a ceiling the async conversion was thought
    to have removed, and taken back out: the premise was wrong. FastAPI's
    `contextmanager_in_threadpool` borrows a threadpool slot only for
    `__enter__`/`__exit__`, and a dependency is solved before its handler queues
    for a slot of its own — so anyio's `CapacityLimiter(40)` never bounded how
    many connections were live.

    Disputed once and now measured — 60 concurrent requests opened 60 backends in
    *both* shapes, while the same 60 holds took two waves sync and one async. The
    limiter shows up in wall time and nowhere in the connection count, so what
    the conversion removed is a throughput bound, not a connection bound, and the
    budget question stands on its own terms rather than as a ceiling to restore.
    Figures and method: `docs/research/async-cancellation-and-connections.md`.

    Reuse also broke two things a per-request connection makes structurally
    impossible. `_only_one_answer` takes a *session*-scoped advisory lock whose
    release is a `finally` that an aborted transaction can skip; closing the
    connection releases it regardless, a returned pooled connection does not
    (psycopg_pool only rolls back, never `DISCARD ALL`). And a pooled connection keeps psycopg's
    default `prepare_threshold`, so statements are PREPAREd server-side and
    survive the `ALTER TABLE` that invalidates them.

    A pool may still be right, but it needs the number nothing here has: what
    the session pooler will actually grant. Measuring that is 112/#242.
    """
    try:
        # The outer bound covers the whole open, DNS included: psycopg resolves
        # the host through the shared executor *before* libpq's own timeout
        # starts, so a queued lookup would otherwise wait unbounded.
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            conn = await psycopg.AsyncConnection.connect(
                settings.database_url, connect_timeout=CONNECT_TIMEOUT_SECONDS
            )
    except (psycopg.OperationalError, TimeoutError) as error:
        # Bounded (112/#242): a pool with no seat free or a pooler that does
        # not answer is a 503 in three seconds, not a request that waits on the
        # pooler's queue or the OS. The driver's words stay out of the answer;
        # the class goes to the log, because a refused password lands here too
        # and must not read as a busy pool to whoever is on call.
        logger.warning("connection refused at open: %s", type(error).__name__)
        raise HTTPException(status_code=503, detail=DB_BUSY) from None
    async with conn:
        await register_vector_async(conn)
        yield conn


# The ledger's day, written once, because everything that means "a day" reads
# it: the cap, its sweep, the remaining-runs figure `/me` reports, how long a
# paused run may be redeemed for, and how long an unkept report is readable
# (035/#136). Two literals would let any of them drift from the others.
LEDGER_HOURS = 24
_LEDGER_WINDOW = f"requested_at > now() - interval '{LEDGER_HOURS} hours'"
_LEDGER_EXPIRED = f"requested_at < now() - interval '{LEDGER_HOURS} hours'"
_EVALUATE = "/evaluate"
# Previewing a panel and buying one are different purchases, counted separately:
# this key bounds previews, `_EVALUATE` bounds panels.
_PREVIEW = "/evaluate-preview"
# One more separate count: how often a caller may make the classifier read a
# sentence of their choosing. Previews do not bound this — the gate lets a
# reader edit as often as they like on one thread — and runs do not either,
# since a refused edit buys nothing. Both doors' checks share the key.
_CHECK = "/evaluate-check"


def _now() -> datetime:
    """Wrapped so tests can move the clock."""
    return datetime.now(UTC)


class _Charge(NamedTuple):
    """One cap to enforce: how many rows this key may hold in the window."""

    endpoint: str
    key: str
    limit: int
    unit: str


class _Spend(NamedTuple):
    """One priced request to charge against the day's global pool (064/#192)."""

    endpoint: str
    usd: Decimal


def _usd(amount: float) -> Decimal:
    """A written dollar figure — a constant, or a configured cap — as Decimal.

    Money is compared in Decimal because float sums drift, and a day of
    charges must land exactly on the cap rather than a hair past it. Via
    str(), or the float's binary error survives the conversion.

    Pass written figures only, never a computed product: price in Decimal
    from the start instead (see `_run_price`).
    """
    return Decimal(str(amount))


def _run_price() -> Decimal:
    """What one run may buy: a vote for every seat the profile is sized to.

    Multiplied in Decimal so the price is exact at any panel size. In float,
    3 votes price at 0.0006000000000000001 — over a cap of exactly 3 votes,
    which would refuse the last run the budget can afford.
    """
    return _usd(USD_PER_VOTE) * settings.panel.size


# Built once: the verifier holds PyJWT's key-set cache, and a per-request
# instance would refetch the project's keys on every call.
_VERIFIER = verifier_from_settings()


_DELETER = deleter_from_settings()


def get_verifier() -> SupabaseVerifier | None:
    """The project's token verifier, or None when sign-in is not configured."""
    return _VERIFIER


def get_account_deleter() -> AccountDeleter | None:
    """The provider's admin client, or None when no elevated key is set."""
    return _DELETER


def _not_signed_in() -> HTTPException:
    """One sentence for every way of arriving without a session."""
    return HTTPException(status_code=401, detail="sign in to run a test")


def caller_id(
    request: Request, verifier: SupabaseVerifier | None = Depends(get_verifier)
) -> str:
    """Who to count — the verified subject id (063/#158).

    A quota counts a `caller`, so the whole limit is worth exactly what that
    identity is worth. It used to be an address our proxy forwarded, which
    bounds a network location rather than a person and costs nothing to change.
    Now it is the `sub` claim of a signature-checked session token: the one
    identity a caller cannot mint without a Google account.

    This runs as a dependency rather than in the shared-secret middleware
    deliberately — 045's middleware guards *the door*, proving a request came
    from our proxy, and it cannot 401 selectively per endpoint or hand a
    subject id to anything. A dependency still refuses before the handler and
    its model calls run, which is what "at the edge" has to mean: a refused
    request costs nothing (013).

    Unconfigured (`SUPABASE_PROJECT_URL` unset) falls back to the pre-auth
    identity so local development and CI run without an auth project. That
    fallback is the honest one: it counts *something* rather than pretending
    to have verified somebody.
    """
    if verifier is None:
        return _unverified_caller(request)
    token = bearer_token(request.headers.get("authorization"))
    if token is None:
        raise _not_signed_in()
    try:
        return verifier.subject(token)
    except SessionUnverifiable:
        # Not 401. A 401 asks the visitor to sign in again, and a fresh token
        # would be checked against the same unreachable key server — so the
        # one remedy the status code suggests is the one that cannot work.
        raise HTTPException(
            status_code=503,
            detail="sign-in cannot be checked right now — please try again shortly",
        ) from None
    except InvalidSession:
        # Same sentence for absent and forged: which one it was is not the
        # caller's business, and the remedy is identical.
        raise _not_signed_in() from None


def _unverified_caller(request: Request) -> str:
    """The pre-auth identity, kept for the unconfigured case only.

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


async def enforce_evaluate_limits(
    request: EvaluateRequest,
    caller: str = Depends(caller_id),
    conn: psycopg.AsyncConnection = Depends(get_conn),
) -> None:
    """Charge for the preview. The panel is never bought here.

    Two purchases, counted separately: a preview buys the gate visit (and the
    one rewrite call, when audience words were written), a panel buys every
    vote it is sized to. The panel is charged after its sentence is judged —
    on accept by `/evaluate/resume`, or in the handler once
    `_approved_on_entry` clears on a run that skips the gate.

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
    # A preview buys at most one model call: the rewrite, when the reader wrote
    # audience words. Controls are read by SQL and no model sees them (094), so
    # a demographics-only run reaches the gate for free — the allowance below
    # still counts the visit, because gate visits bound probing, not spend.
    charges = [
        _Charge(_PREVIEW, caller, settings.evaluate_previews_per_day, "previews")
    ]
    preview_usd = Decimal(0)
    if request.audience.strip() and not request.reading_accepted:
        # The rewrite that writes the gate's draft. Not on the skip path: there
        # the validator forces the approved sentence through, nothing is
        # rewritten, and the one call that does happen — the check — is charged
        # where it fires, in `_approved_on_entry`.
        preview_usd = _usd(USD_PER_ROLEPLAY)
    # None, not a zero row: a $0 spend would still take the pool's advisory
    # lock and leave a ledger row nobody reads.
    spend = _Spend(_PREVIEW, preview_usd) if preview_usd else None
    # No panel is bought here, on either path. A panel is bought only below the
    # check that judges what it would be told, so a refused sentence never
    # costs a run: `/evaluate/resume` on accept, `/evaluate` for a run that
    # skips the gate.
    await _charge_ledger(conn, *charges, spend=spend)


async def enforce_turn_limit(
    request: ChatRequest,
    caller: str = Depends(caller_id),
    conn: psycopg.AsyncConnection = Depends(get_conn),
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
    await _charge_ledger(
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
        # A measured price, not an upper bound: USD_PER_TURN covers the worst
        # measured *low-effort* turn — the effort the analyst ships at — and
        # what stops a turn out-spending it unboundedly is
        # ANALYST_MAX_COMPLETION_TOKENS times the declared per-turn call
        # budget, analyst.CALLS_PER_TURN (090/#195, 052/#149).
        spend=_Spend("/chat", _usd(USD_PER_TURN)),
    )


def _panel_purchase(caller: str) -> tuple[_Charge, Decimal]:
    """One panel: a slot from the day's runs, priced at the votes it may buy."""
    return (
        _Charge(_EVALUATE, caller, settings.evaluate_runs_per_day, "runs"),
        _run_price(),
    )


def _capped(charge: _Charge) -> HTTPException:
    """The refusal a full cap gets. The sentence is this codebase's own and
    names the remedy; the counted identity never travels back."""
    return HTTPException(
        status_code=429,
        detail=(
            f"limit reached ({charge.limit} {charge.unit} per day) — try again tomorrow"
        ),
    )


async def _refuse_if_run_capped(conn: psycopg.AsyncConnection, caller: str) -> None:
    """Refuse a caller with no runs left before anything is spent on them.

    Advisory, and deliberately so: `_charge_ledger` is still the only place a
    cap is enforced, and losing the race here just means a check was read for a
    run that is then refused. What this buys is the ordinary case. The panel is
    bought *after* its sentence is judged, so without this a caller at their cap
    would pay for a model call on a run that could never start — and 013's rule
    that a refused request costs nothing would hold only for the schema.
    """
    charge, _ = _panel_purchase(caller)
    if charge.limit <= 0:
        return
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM request_ledger"
            f" WHERE endpoint = %s AND caller = %s AND {_LEDGER_WINDOW}",
            (charge.endpoint, charge.key),
        )
        row = await cur.fetchone()
    # Nothing was written, so this ends the read's transaction rather than
    # leaving it open across the model call that follows.
    await conn.rollback()
    if (int(row[0]) if row else 0) >= charge.limit:
        raise _capped(charge)


async def _buy_panel(conn: psycopg.AsyncConnection, caller: str) -> None:
    """The moment a panel is bought: one slot from the day's runs, priced at
    the votes it may buy. Both doors call this, and both call it *after* the
    sentence the panel would be told has been judged."""
    charge, price = _panel_purchase(caller)
    await _charge_ledger(conn, charge, spend=_Spend(_EVALUATE, price))


async def _charge_ledger(
    conn: psycopg.AsyncConnection, *charges: _Charge, spend: _Spend | None = None
) -> None:
    """Enforce every cap, then record one attempt against each — or refuse.

    Count-then-insert is not a limit under load: READ COMMITTED cannot see
    another transaction's uncommitted rows, so simultaneous requests all read
    the same count and all pass — 10 concurrent requests took 7 slots out of a
    limit of 3, measured. Advisory locks make the database arbitrate instead.

    That measurement was taken when handlers ran in a threadpool (111/#240 made
    them coroutines on one loop). The mechanism it demonstrates is the
    isolation level's, not the threadpool's, so the conclusion survives the
    conversion — but the figure was produced under an arrangement this codebase
    no longer has, and re-measuring it belongs to whoever next doubts the
    locks.

    - Locks are held to the end of the transaction and always taken in the
      same order (pool first, then per-key sorted), so callers charging the
      same keys cannot deadlock.
    - Every cap is checked before any is recorded, so a request refused by one
      cap does not consume another's budget.
    - `limit <= 0` — or a pool cap of 0 — disables that cap, the escape hatch
      for local iteration.
    - `spend` charges the day's global pool (064/#192): one budget for every
      caller and both paid endpoints, since a new caller costs nothing to
      mint. Checked after the per-key caps, so a caller who has hit their own
      limit is told which one.
    - Writes sweep expired rows, so the ledger never keeps rows nobody will
      read again (040).
    """
    active = [charge for charge in charges if charge.limit > 0]
    cap = _usd(settings.global_daily_cap_usd)
    pooled = spend if spend is not None and cap > 0 else None
    if not active and pooled is None:
        return
    async with conn.cursor() as cur:
        if pooled is not None:
            await cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", ("spend-pool",)
            )
        for charge in sorted(active):
            await cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"{charge.endpoint}:{charge.key}",),
            )
        for charge in active:
            await cur.execute(
                "DELETE FROM request_ledger WHERE endpoint = %s AND caller = %s"
                f" AND {_LEDGER_EXPIRED}",
                (charge.endpoint, charge.key),
            )
            await cur.execute(
                "SELECT count(*) FROM request_ledger"
                f" WHERE endpoint = %s AND caller = %s AND {_LEDGER_WINDOW}",
                (charge.endpoint, charge.key),
            )
            row = await cur.fetchone()
            if (int(row[0]) if row else 0) >= charge.limit:
                # Release the locks now rather than at request teardown; the
                # discarded sweep is opportunistic and costs nothing.
                await conn.rollback()
                raise _capped(charge)
        if pooled is not None:
            await cur.execute(
                "DELETE FROM spend_ledger WHERE spent_at < now()"
                f" - interval '{LEDGER_HOURS} hours'"
            )
            await cur.execute(
                "SELECT coalesce(sum(usd), 0) FROM spend_ledger"
                " WHERE spent_at > now() - interval '24 hours'"
            )
            row = await cur.fetchone()
            spent = Decimal(row[0]) if row else Decimal(0)
            if spent + pooled.usd > cap:
                await conn.rollback()
                # Names the remedy, never the figure — a number left would
                # give an abuser a progress bar.
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "today's budget is spent — paid runs return tomorrow,"
                        " and the demo report stays free to read"
                    ),
                )
        for charge in active:
            await cur.execute(
                "INSERT INTO request_ledger (endpoint, caller) VALUES (%s, %s)",
                (charge.endpoint, charge.key),
            )
        if pooled is not None:
            await cur.execute(
                "INSERT INTO spend_ledger (endpoint, usd) VALUES (%s, %s)",
                (pooled.endpoint, pooled.usd),
            )
    await conn.commit()


def tracing_enabled() -> bool:
    """Whether this process is really sending traces.

    A dependency so a test can report a traced deployment without turning
    tracing on for the test run.
    """
    return _TRACING


@app.get("/health")
async def health(
    verifier: SupabaseVerifier | None = Depends(get_verifier),
    tracing: bool = Depends(tracing_enabled),
) -> dict[str, str]:
    """Ungated on purpose — the keep-warm ping and the daily check both hit it.

    `auth` reports whether sign-in is actually being *enforced*, which is the
    one failure this deployment could otherwise not see: the frontend and the
    backend are configured from different places, so a backend missing
    SUPABASE_PROJECT_URL still serves a frontend that shows the sign-in button,
    takes the visitor through Google, sends the token — and then ignores it,
    falling back to counting an address. Everything looks like it works, and
    the per-account limit silently is not one.
    """
    return {
        "status": "ok",
        "db": "up" if await asyncio.to_thread(check_connection) else "down",
        "auth": "off" if verifier is None else "on",
        # The form's disclosure line reads this. One deployment answers for
        # both, so the page cannot disagree with what is actually happening.
        "tracing": "on" if tracing else "off",
    }


@app.get("/me")
async def me(
    caller: str = Depends(caller_id),
    conn: psycopg.AsyncConnection = Depends(get_conn),
) -> dict[str, int]:
    """What this account has left to spend today (092/#197).

    A caller's own count is safe to say, and the report the day's pool refuses
    with is not: `_charge_ledger` withholds the pool figure deliberately,
    because a shared number counting down is a progress bar for whoever is
    draining it. This one counts only the reader's own runs, which they could
    have counted themselves.

    Reads without charging: no row is written, so opening the page does not
    spend a run.

    The rail's figures ride along (124/#291), so the form can say "this test
    will not be saved" before the run rather than after it. Counted the way
    the save path counts, so the notice and the post-run warning agree.
    """
    limit = settings.evaluate_runs_per_day
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM request_ledger"
            f" WHERE endpoint = %s AND caller = %s AND {_LEDGER_WINDOW}",
            (_EVALUATE, caller),
        )
        row = await cur.fetchone()
    used = int(row[0]) if row else 0
    return {
        "runs_per_day": limit,
        "runs_remaining": max(0, limit - used),
        "saved_tests": await count_reports(conn, owner=caller),
        "saved_tests_cap": settings.saved_tests_per_user,
    }


@app.delete("/me", status_code=204)
async def forget_me(
    conn: psycopg.AsyncConnection = Depends(get_conn),
    caller: str = Depends(caller_id),
    deleter: AccountDeleter | None = Depends(get_account_deleter),
) -> Response:
    """Erase the account, on request (063/#158).

    Mostly cheap, because the subject-id rule means there is little else to look
    at: the address lives in the provider's `auth.users` table and this call
    removes it.

    **One exception, and it is the reason this is not a one-liner (117/#252).**
    `tests` holds the customer's own content — their headline text, and the
    phrases their audience reading was quoted from — so those rows are deleted
    here. Every clause of the argument below fails for them: a report is
    personal data whether or not the account exists, it does not expire within
    the day, and deleting one grants no budget, so there is nothing to sell.

    What stays behind is `request_ledger` rows holding an opaque id and a
    timestamp — and they stay behind *on purpose*, against 063's original
    "delete our rows" wording:

    - **They are not personal data once the account is gone.** The id linked to
      a person only through `auth.users`, which this call just erased.
    - **They expire within the day anyway**, swept by the next write.
    - **Wiping them would sell runs.** A deleted user's access token stays
      signature-valid until it expires — Supabase is explicit that deletion
      "cannot retroactively invalidate an access token that was already issued"
      — so a delete that also cleared the ledger would hand that still-working
      token a fresh budget, once per call, for free.

    That last point is worth being honest about in the other direction too: a
    person can still sign in again and be issued a *new* subject id with a
    fresh budget. A per-account limit raises the price of a reset from "change
    a header" to "delete and re-create an account"; it does not make it
    infinite. The day's global pool (064/#192) remains the real ceiling, which
    is exactly what 089 said when it declined to treat per-caller limits as
    one.
    """
    if deleter is None:
        # Refuses the whole operation, reports included. Deliberate: deleting a
        # customer's stored tests while leaving the account that owns them is
        # worse than doing neither, and they can still remove them one at a time
        # through `DELETE /tests/{id}` (117/#252, review).
        raise HTTPException(
            status_code=503,
            detail="account deletion is not available on this deployment",
        )
    try:
        await asyncio.to_thread(deleter.delete, caller)
    except DeletionFailed:
        raise HTTPException(
            status_code=502,
            detail="the account could not be deleted — nothing was changed",
        ) from None
    # After the provider, not before: a local delete that ran and then failed to
    # erase the account would take the customer's reports while leaving the
    # account that owned them.
    #
    # And handled, because by here the account is already gone and the subject
    # id with it — so no retry of this call, and no `DELETE /tests/{id}`, can
    # ever reach these rows again. A bare 500 would read as "it did not happen"
    # over a state where half of it did (117/#252, review).
    try:
        await delete_reports_of(conn, owner=caller)
    except psycopg.Error:
        logger.exception("account %s was erased but its stored tests were not", caller)
        raise HTTPException(
            status_code=502,
            detail=(
                "the account was erased, but its stored tests could not be "
                "deleted — they are orphaned rather than reachable, and clearing "
                "them now needs an operator. Nothing was left signed in."
            ),
        ) from None
    return Response(status_code=204)


class StoredTest(BaseModel):
    """One row of the customer's own rail (117/#252).

    Three fragments of a stored report rather than the report: the rail renders
    `"A" vs "B"` and a phrase derived from the verdict, and searches on the two
    headlines. Sending whole reports to draw a list of labels would ship every
    vote and reason the customer has ever bought.

    **No verdict label here, deliberately.** The phrase the rail shows ("too
    close to call", "71% preferred the first") is derived at render time by
    `frontend/app/lib/verdict.ts`, which already owns that rule for the report
    itself — a second implementation would be a second threshold, and 020 keeps
    the label out of the payload.

    `verdict` and `tally` travel as their models rather than as raw JSON, so a
    fragment that stopped matching its model fails here instead of in the rail.
    """

    test_id: str
    created_at: datetime
    variants: dict[str, str]
    verdict: PanelVerdict
    tally: VoteTally


# Derived, not chosen (118/#253): the largest page of worst-case rows — both
# headlines at MAX_HEADLINE_CHARS, the request validator's own bound — that
# fits TCP's initial congestion window of 10 segments x 1460 B MSS (RFC 6928,
# April 2013). So the rail's first paint costs one round trip even on a cold
# connection, whatever a customer wrote. Measured 2026-08-31: 1,625 B/row;
# `test_the_default_page_is_the_largest_that_fits_one_round_trip` redoes the
# arithmetic, so a field added to `StoredTest` reopens it instead of silently
# outgrowing the window.
TESTS_PAGE_ROWS = 14600 // 1625


class StoredTestPage(BaseModel):
    """One page of the rail, newest first.

    `next_cursor` is present when the read that built this page saw a row
    below it — near-always, following it fetches something, though a delete
    landing between the two reads can still empty the next page. Opaque to
    clients:
    it encodes a position (a row's instant and id), and a client that parsed it
    would inherit the encoding as API.
    """

    tests: list[StoredTest]
    next_cursor: str | None


def _tests_cursor(row: StoredTest) -> str:
    return base64.urlsafe_b64encode(
        f"{row.created_at.isoformat()}|{row.test_id}".encode()
    ).decode()


def _tests_cursor_position(cursor: str) -> tuple[datetime, str]:
    """422 on anything unreadable — a cursor is only ever one we minted, so a
    garbled one is a caller error, never a reason to 500. What it names is not
    trusted: ownership is a WHERE clause in `list_reports`, so a forged cursor
    moves where the caller's own list resumes and nothing else."""
    try:
        moment, _, test_id = (
            base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        )
        if not test_id:
            raise ValueError("no separator")
        return datetime.fromisoformat(moment), test_id
    except ValueError:
        raise HTTPException(status_code=422, detail="unreadable cursor") from None


@app.get("/tests")
async def my_tests(
    cursor: str | None = None,
    limit: int = Query(default=TESTS_PAGE_ROWS, ge=1, le=TESTS_PAGE_ROWS),
    conn: psycopg.AsyncConnection = Depends(get_conn),
    caller: str = Depends(caller_id),
) -> StoredTestPage:
    """One page of this account's finished tests, newest first.

    One row more than the page is fetched, so "is there more" is answered by
    the same read that builds the page — a COUNT would race every new run.
    """
    before = _tests_cursor_position(cursor) if cursor is not None else None
    rows = await list_reports(conn, owner=caller, limit=limit + 1, before=before)
    tests = [StoredTest.model_validate(row) for row in rows[:limit]]
    return StoredTestPage(
        tests=tests,
        next_cursor=_tests_cursor(tests[-1]) if len(rows) > limit else None,
    )


@app.get("/tests/{test_id}")
async def my_test(
    test_id: str,
    conn: psycopg.AsyncConnection = Depends(get_conn),
    caller: str = Depends(caller_id),
) -> EvaluateResponse:
    """One stored report, whole — the read that gets a report back after the
    page that was drawing it crashed (049/#147).

    404 for a test that is not this caller's, and the *same* 404 a missing one
    gets: answering differently would say whether an id exists, and a test id is
    not a credential.
    """
    report = await load_report(conn, test_id=test_id, owner=caller)
    if report is None:
        raise HTTPException(status_code=404, detail="no such test")
    return EvaluateResponse.model_validate(report)


@app.delete("/tests/{test_id}", status_code=204)
async def forget_test(
    test_id: str,
    conn: psycopg.AsyncConnection = Depends(get_conn),
    caller: str = Depends(caller_id),
) -> Response:
    """Delete one of this account's tests, for good.

    A real delete rather than a flag — a hidden row would leave the customer's
    headline text in a table they asked to be rid of. 404 when nothing went,
    which is also what a second click gets.
    """
    if not await delete_report(conn, test_id=test_id, owner=caller):
        raise HTTPException(status_code=404, detail="no such test")
    return Response(status_code=204)


def get_checkpointer(request: Request) -> BaseCheckpointSaver:
    """The lifespan's process-lifetime saver, exposed as a dependency so tests
    can swap in an InMemorySaver — thread durability is test_analyst's
    subject, not a tax on every endpoint test."""
    return request.app.state.checkpointer


class PausedRun(BaseModel):
    """The run is holding at the panel gate, waiting for a human (076/#166)."""

    status: Literal["paused"] = "paused"
    # Travels to the client and back: the pause outlives the request, and the
    # process.
    thread_id: str
    preview: PanelPreview


class CompletedRun(EvaluateResponse):
    """A finished run. `status` is additive — every older field is still here.

    `thread_id` is the run's own id, which is also the stored test's: the page
    names it to the analyst and to the recovery read (035/#136). On the
    response only, like `status` — a stored report does not carry its own key.
    """

    status: Literal["complete"] = "complete"
    thread_id: str


def _outcome(
    state: dict,
    *,
    thread_id: str,
    variants: dict[str, str],
    credit: float | None,
) -> PausedRun | CompletedRun:
    """Read the graph's final state, for both start and resume.

    Either call can return either shape: a resume pauses again when the reading
    was adjusted.
    """
    paused = state.get("__interrupt__")
    # The same id the trace is labelled with, so a run in LangSmith and the
    # lines it wrote here can be paired. The vote node stamps its votes with
    # this id too, so the panel's usage line carries it as `test_id`.
    logger.info("evaluate: %s", "paused at the panel gate" if paused else "complete")
    if paused:
        return PausedRun(
            thread_id=thread_id, preview=PanelPreview.model_validate(paused[0].value)
        )
    result = state["result"]
    return CompletedRun(
        thread_id=thread_id,
        usage=RunUsage(**asdict(total_usage(result.votes.usage))),
        timings=RunTimings(step_seconds=state.get("step_seconds", {})),
        verdict=result.verdict,
        tally=result.tally,
        counts=result.counts,
        query=result.selection.query,
        notices=budget_notice(credit, size=settings.panel.size) + result.notices,
        stop_reason=result.stop_reason,
        variants=variants,
        votes=votes_with_voters(result.votes.records, result.selection.panel),
    )


async def _kept(
    outcome: PausedRun | CompletedRun,
    *,
    conn: psycopg.AsyncConnection,
    state: dict,
    caller: str,
) -> PausedRun | CompletedRun:
    """Store a finished report for the account that ran it (117/#252), and
    decide whether the rail keeps it (085/#176, 035/#136).

    **Best-effort, and never fails the response.** When this runs the votes are
    already bought, so a raised write would lose the report *and* the run —
    which is 049/#147's own complaint arriving through the mechanism meant to
    answer it. The customer holds the report in the body either way; what a
    failure costs is the copy, and that is the cheaper loss by a whole run.

    A paused run is not kept: it has bought nothing and has no verdict.

    `caller` is the owner, and what that is worth is what `caller_id` is worth.
    With a verifier configured it is a signature-checked subject; unconfigured,
    it is the pre-auth identity, which is only trustworthy because the edge
    secret proved the request came from our proxy — which is why `/tests` is in
    `_GUARDED_PATHS`. In that unconfigured state the identity is address-derived,
    so two visitors behind one address share a rail. Acceptable where it applies
    (local development and the documented interim deploy) and not in production,
    where signing in is required to run at all.

    `status` and `thread_id` are excluded because they belong to the HTTP
    answer rather than to the record — a row carrying them would be a stored
    response, not a stored test.
    """
    if not isinstance(outcome, CompletedRun):
        return outcome
    result = state["result"]
    test_id = result.test_id
    try:
        # The save cap (085/#176): at the cap the save is refused and the
        # response says so — never an old test evicted, because deletion is
        # the user's own act. Counted excluding this test's own id, so a
        # re-completed run that is already kept is not scolded for a row it
        # is not adding. Check-then-act, unguarded on purpose: two runs
        # landing at count nine both save, and the cap reads eleven. That
        # money-shaped hole is why _only_one_answer holds a row lock; a
        # storage quota overshooting by a day's runs is not worth one.
        cap = settings.saved_tests_per_user
        # The sweep rides on the write, like the ledgers': unkept rows older
        # than the ledger's day go before this run's row arrives.
        await sweep_unkept_reports(conn, older_than_hours=LEDGER_HOURS)
        kept = await count_reports(conn, owner=caller, excluding=test_id) < cap
        if not kept:
            # The sentence states the limit, never the count: rows can exceed
            # a lowered cap, and a number nobody measured is not spoken. The
            # remedy only exists while there is a cap to make room under. Its
            # pre-run twin is in frontend/app/components/allowance.tsx
            # (124/#291): change both together.
            message = (
                "This test was not saved: an account keeps at most "
                f"{cap} saved test{'s' if cap != 1 else ''}, and your rail "
                "is full. The full report below is still yours to read now."
            )
            if cap > 0:
                message += " Delete a saved test to make room for the next one."
            outcome = outcome.model_copy(
                update={
                    "notices": outcome.notices
                    + (Notice(severity="warning", message=message),)
                }
            )
        # Stored either way; `kept` is what the cap decides (035/#136).
        await store_report(
            conn,
            test_id=test_id,
            owner=caller,
            # The run's own notices, not the response's: `_outcome` prepends
            # `budget_notice`, which quotes the operator's OpenRouter balance at
            # one instant. Stored, a report reopened weeks later would show that
            # figure as if current — and it was never a fact about the test
            # (117/#252, review).
            report=outcome.model_copy(update={"notices": result.notices}).model_dump(
                mode="json", exclude={"status", "thread_id"}
            ),
            kept=kept,
        )
    except Exception:
        # Logged with the id so the loss is traceable to a run, and swallowed on
        # purpose — see the docstring.
        logger.exception("could not keep the report", extra={"test_id": test_id})
    return outcome


async def _run_graph(graph, payload, thread_id: str):
    """Run the graph and map its refusals to status codes.

    Every message forwarded here is this codebase's own: `EmptyPanel` is a fixed
    sentence and `NoVotes` carries exception type names only, never provider or
    model text.
    """
    try:
        return await graph.ainvoke(
            payload,
            {
                "configurable": {"thread_id": thread_id},
                # Repeated as metadata because only `model` and `checkpoint_ns`
                # are copied out of `configurable` for a trace. This is the one
                # handle a LangSmith run and this request's log lines share.
                "metadata": {"thread_id": thread_id},
            },
        )
    except UnsafeInput as error:
        # 400, not 422: the text is well-formed; what it says was refused.
        raise HTTPException(status_code=400, detail=str(error)) from error
    except EmptyPanel as error:
        # The target names an audience this pool cannot serve: fix the request.
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RolePlayRefused as error:
        # One of our own fixed sentences, naming the remedy. The refused text is
        # never echoed, no panel is drawn, and no run is consumed: this only
        # fires on the gated path, whose charge so far is a preview — a
        # separate and looser allowance. (The skip path never reaches here: its
        # instruction was judged at the API boundary, above the purchase.)
        raise HTTPException(status_code=422, detail=error.sentence) from error
    except GeneratorFault as error:
        # Ours, not the reader's: the model missed our schema twice (081/#169).
        raise HTTPException(status_code=502, detail=error.sentence) from error
    except NoVotes as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except OutOfCredit as error:
        raise HTTPException(status_code=402, detail=str(error)) from error


class DemoRun(CompletedRun):
    """A replayed run, carrying the captured run's own per-step seconds in
    `timings` — the frontend replays those, because inventing durations is
    forbidden (061) — plus the day the run was bought, which the honesty line
    names."""

    captured_at: str


@app.get("/demo/{case}")
async def demo(
    case: str,
    conn: psycopg.AsyncConnection = Depends(get_conn),
) -> DemoRun:
    """Serve one demo case: a captured run, replayed through the real graph.

    Deliberately outside `caller_id`, the edge guard and every budget — the
    demo spends nothing, and the refusal screens promise the sample stays
    free to read precisely when budgets are spent. No model is called: the
    panel is a replay, the screener is off because this pair was screened
    when the capture bought it, and the generator is unreachable because the
    audience is empty. Not `_kept` either — nobody owns a demo report, and
    the rail's samples are links to this route, not rows in `tests`. The
    checkpointer is per-request and in memory for the same reason: a replay
    never pauses, so durability would only grow the checkpoint table by one
    anonymous thread per click.
    """
    if case not in DEMO_CASES:
        raise HTTPException(status_code=404, detail="no such demo")
    fixture = load_fixture(case)
    if fixture is None:
        raise HTTPException(
            status_code=503, detail="this demo is not seeded on this deployment"
        )
    personas = await load_personas_by_id(
        conn, [vote.persona_id for vote in fixture.votes]
    )
    thread_id = str(uuid4())
    graph = build_evaluate_graph(
        conn=conn,
        llm=ReplayPanel(fixture, {render_persona_prompt(p): p.id for p in personas}),
        screener=None,
        generator=UnreachableGenerator(),
        checkpointer=InMemorySaver(),
    )
    # The run's lines — a refused screen, a vote worker's retry, the panel's
    # usage line, the outcome — carry its thread id (047/#145).
    with bind_thread(thread_id):
        state = await _run_graph(
            graph,
            {
                "query": settled_query(PanelEdit()),
                "notices": [CROSS_SECTION_NOTICE],
                "audience": "",
                "instruction": "",
                "variants": fixture.variants,
                # The capture's size, not this deployment's profile: the replay
                # must ask for the panel the votes were bought for.
                "size": fixture.size,
                "reading_accepted": True,
                # A replay is nobody's: "" tells the vote node to leave the ledger
                # alone entirely — no anonymous rows written, no account's read
                # (086/#177).
                "owner": "",
                "started_at": _now().isoformat(),
            },
            thread_id,
        )
        outcome = _outcome(
            state, thread_id=thread_id, variants=fixture.variants, credit=None
        )
        if not isinstance(outcome, CompletedRun):  # pragma: no cover
            # reading_accepted means no gate; a pause here is a broken premise.
            raise HTTPException(status_code=500, detail="the demo run did not finish")
        return DemoRun(
            **outcome.model_dump(exclude={"timings"}),
            # The replay's own clock ran in milliseconds; the reader is shown
            # the bought run's seconds, never the replay's.
            timings=RunTimings(step_seconds=fixture.step_seconds),
            captured_at=fixture.captured_at,
        )


@app.post("/evaluate")
async def evaluate(
    request: EvaluateRequest,
    _limit: None = Depends(enforce_evaluate_limits),
    caller: str = Depends(caller_id),
    llm: PanelLLM = Depends(get_panel_llm),
    conn: psycopg.AsyncConnection = Depends(get_conn),
    credit: float | None = Depends(get_remaining_credit),
    screener: Screener | None = Depends(get_screener),
    generator: RolePlayGenerator = Depends(get_generator),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
) -> PausedRun | CompletedRun:
    """Start a run. Stops at the panel gate unless the reading was approved.

    The reading is settled here, not translated: the controls are the query
    (094), so no model reads them and the graph starts from a done deal. The
    panel is charged where it is bought — on accept, or here when the reading
    arrives approved and there is no gate to stop at — and always after its
    sentence is judged, so a refusal never costs a run on either door.
    """
    # The skip path's two money moves straddle the check, and each side of it
    # keeps one rule: the cap is probed above, so a caller with no runs left
    # pays nothing to be told so; the panel is bought below, so a sentence that
    # will never run costs no run. The check itself is charged either way.
    # A brought id is honoured only if nothing lives under it: reusing a live
    # thread would run a new panel over its checkpoints. Refused above every
    # charge, so the mistake costs nothing — and ids are unguessable, so the
    # 409 confirms nothing a stranger could use.
    if request.thread_id is not None:
        taken = await checkpointer.aget(
            {"configurable": {"thread_id": request.thread_id}}
        )
        if taken is not None:
            raise HTTPException(
                status_code=409,
                detail="that run id is already in use — mint a fresh one",
            )
    if request.reading_accepted:
        await _refuse_if_run_capped(conn, caller)
    instruction = await _approved_on_entry(conn, request, generator, caller)
    if request.reading_accepted:
        await _buy_panel(conn, caller)
    variants = {"a": request.headline_a, "b": request.headline_b}
    thread_id = request.thread_id or str(uuid4())
    graph = build_evaluate_graph(
        conn=conn,
        llm=llm,
        screener=screener,
        generator=generator,
        checkpointer=checkpointer,
    )
    # Only this layer knows every control was left alone — the query it builds
    # is identical to one that asked for JP-to-DE everyone — so the
    # cross-section reading is said here or nowhere.
    untargeted = request.target == PanelEdit()
    # The run's lines — a refused screen, a vote worker's retry, the panel's
    # usage line, the outcome — carry its thread id (047/#145).
    with bind_thread(thread_id):
        state = await _run_graph(
            graph,
            {
                "query": settled_query(request.target),
                "notices": [CROSS_SECTION_NOTICE] if untargeted else [],
                "audience": request.audience,
                "instruction": instruction,
                "variants": variants,
                "size": settings.panel.size,
                "reading_accepted": request.reading_accepted,
                "owner": caller,
                "started_at": _now().isoformat(),
            },
            thread_id,
        )
        return await _kept(
            _outcome(state, thread_id=thread_id, variants=variants, credit=credit),
            conn=conn,
            state=state,
            caller=caller,
        )


@asynccontextmanager
async def _only_one_answer(
    conn: psycopg.AsyncConnection, thread_id: str
) -> AsyncIterator[None]:
    """Hold a run while it is being answered, or refuse.

    A session lock, not a transaction lock: the vote loop commits per chunk, and
    a transaction lock would be released by the first of them. Verified rather
    than assumed — `pg_advisory_xact_lock` is gone by the time the second chunk
    starts.

    The release below is belt to the connection's braces. Postgres drops a
    session lock when the backend exits, so `get_conn` closing this connection
    at the end of the request releases it whatever happens here — including from
    an aborted transaction. That is what lets the `finally` give up quietly. All
    of it measured: `docs/research/async-cancellation-and-connections.md`.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s))", (f"resume:{thread_id}",)
        )
        row = await cur.fetchone()
    if not (row and row[0]):
        raise HTTPException(
            status_code=409, detail="this run is already being answered"
        )
    try:
        yield
    finally:
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))", (f"resume:{thread_id}",)
                )
        except psycopg.Error as failed:
            # Never at the cost of the error being unwound. A run that left the
            # transaction aborted made this unlock raise `InFailedSqlTransaction`
            # *during handling of* the original — so `_run_graph`'s curated 402,
            # 422 or 502 became an opaque 500, readable only as `__context__`.
            # Giving up costs nothing the connection close does not already
            # cover, and the release is only ever early.
            logger.warning(
                "could not release the resume lock (%s); the connection close"
                " will release it",
                failed.__class__.__name__,
            )


def _edit_to_settle(request: ResumeRequest, values: dict) -> str | None:
    """The reader's edited sentence, or None when there is nothing to classify.

    One predicate, because two places depend on the same answer and they must
    agree forever: what gets *checked* and what gets *charged*. If they ever
    drifted, one direction is a free classifier call and the other is a charge for
    a check that never happened.

    None covers three cases that all mean "no new sentence to judge": the field
    was not touched, it holds what the draft already said — its verdict was
    reached when it was written — or it was cleared, which is a decision rather
    than a sentence.
    """
    edited = request.instruction
    if edited is None or not edited.strip():
        return None
    if edited == values.get("instruction", ""):
        return None
    return edited


def _check_purchase(caller: str) -> _Charge:
    """One classifier reading, from the caller's daily allowance of them."""
    return _Charge(
        _CHECK,
        caller,
        settings.evaluate_checks_per_caller_per_day,
        "instruction checks",
    )


async def _checked_or_refused(
    conn: psycopg.AsyncConnection,
    generator: RolePlayGenerator,
    caller: str,
    sentence: str,
) -> str:
    """Pay for one classifier reading, make it, and refuse what it refuses.

    One function, because both doors owe the same two things and they must not
    drift apart: the check is always paid for — an unmetered refusal path is a
    free probe — and it always sits above the panel purchase, so a sentence
    that will never run costs no run.

    Returns the caller's own string when the verdict is clean. A refusal is one
    of our own fixed sentences naming the remedy; the refused text is never
    echoed.
    """
    await _charge_ledger(
        conn,
        _check_purchase(caller),
        spend=_Spend(_EVALUATE, _usd(USD_PER_ROLEPLAY)),
    )
    try:
        checked = await asyncio.to_thread(generator.check, instruction=sentence)
    except GeneratorFault as error:
        raise HTTPException(status_code=502, detail=error.sentence) from error
    if checked.refusal is not None:
        raise HTTPException(status_code=422, detail=checked.refusal_sentence)
    return checked.instruction


async def _approved_on_entry(
    conn: psycopg.AsyncConnection,
    request: EvaluateRequest,
    generator: RolePlayGenerator,
    caller: str,
) -> str:
    """Classify an instruction the client says was already approved.

    Client-supplied, so untrusted, so judged — a claim of prior approval is not
    evidence of it. Charged like any other check, and it runs above the panel
    purchase, so a refusal here costs the check and nothing else — the same
    deal the gate's edit path offers. Reaching a refusal means the client
    changed the sentence after it was approved.
    """
    if not (request.instruction or "").strip() or not request.audience.strip():
        return ""
    return await _checked_or_refused(conn, generator, caller, request.instruction or "")


async def _classify_edit(
    conn: psycopg.AsyncConnection,
    request: ResumeRequest,
    values: dict,
    generator: RolePlayGenerator,
    caller: str,
) -> str:
    """Judge the reader's edited sentence, above the charge for the panel.

    Above it deliberately, and for the reason the empty-panel refusal above is:
    a sentence that will never be run must cost no run. 094 says so twice — "no
    vote bought, and the refusal is not charged to the caller's allowance" — and
    a reader iterating on their own wording would otherwise spend the day's
    allowance on panels nobody polled.

    On refusal the run stays paused, so the remedy is advice the reader can
    act on.
    """
    edited = _edit_to_settle(request, values)
    if edited is None:
        return ""
    return await _checked_or_refused(conn, generator, caller, edited)


def _edited(request: ResumeRequest, values: dict) -> TargetQuery | None:
    """The edited reading, when the gate's answer carries one."""
    if request.query is None:
        return None
    return settled_query(request.query)


def _expired(started_at: str | None) -> bool:
    """Has this pause outlived the window a preview is honoured for?

    The window is kept from the gate's original design; the reason written for
    it there — that the run's charge had already been swept — no longer holds,
    because the panel is now charged on accept. Whether a pause should expire at
    all is the gate's own question, not this change's, so the behaviour stands
    unchanged rather than being re-argued here.

    Measured from when the run started, not from its latest checkpoint, so a
    free adjust every so often cannot keep a pause alive forever. An unreadable
    timestamp counts as expired — refusing costs a click.
    """
    if started_at is None:
        return True
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return True
    return _now() - started > timedelta(hours=LEDGER_HOURS)


@app.post("/evaluate/resume")
async def resume_evaluate(
    request: ResumeRequest,
    caller: str = Depends(caller_id),
    llm: PanelLLM = Depends(get_panel_llm),
    conn: psycopg.AsyncConnection = Depends(get_conn),
    credit: float | None = Depends(get_remaining_credit),
    screener: Screener | None = Depends(get_screener),
    generator: RolePlayGenerator = Depends(get_generator),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
) -> PausedRun | CompletedRun:
    """Answer the panel gate: accept and buy the votes, or adjust the reading.

    - **Only the owner.** A thread id is not a credential — it travels through
      logs, screenshots and support pastes. Anything but the caller who started
      the run gets the same 404 an unknown id gets, so the endpoint never
      confirms that someone else's run exists.
    - **Only at the gate.** A run that died inside the vote node is still
      "pending", and resuming it would re-enter the paid node for free.
    - **One at a time.** Check-then-act is no guard under load: without the lock,
      simultaneous accepts all pass the check and each buys the whole panel
      against a single charge.
    - **Charged here**, on accept, because this is where a panel is bought. The
      preview was charged when the run started; adjusting adds nothing.
    - Adjust is unbounded. Re-selecting is pure SQL and buys nothing, and an
      adjust never reaches the charge above.
    """
    graph = build_evaluate_graph(
        conn=conn,
        llm=llm,
        screener=screener,
        generator=generator,
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": request.thread_id}}
    # The run's lines — the lock, the graph, the outcome — carry its thread id
    # (047/#145), the same one its first request logged under.
    with bind_thread(request.thread_id):
        async with _only_one_answer(conn, request.thread_id):
            snapshot = await graph.aget_state(config)
            values = snapshot.values or {}
            # One sentence for "no such run" and "not yours": which it was is not
            # the caller's business.
            if snapshot.next != ("confirm",) or values.get("owner") != caller:
                raise HTTPException(
                    status_code=404, detail="no run is waiting for you on that id"
                )
            if _expired(values.get("started_at")):
                raise HTTPException(
                    status_code=410,
                    detail="this panel has expired — start the test again to see a fresh one",
                )
            if request.action == "accept" and not values.get("panel"):
                # The graph would send this straight back to the gate: there is
                # nobody to ask. Refused above the charge, so a reading that can
                # never vote costs nothing. (Unsafe headline text is refused later,
                # inside `vote`, and does spend a run — as it did before the gate
                # existed.)
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "nobody in the pool matches that reading — widen it and look again"
                    ),
                )
            approved = ""
            if request.action == "accept":
                # Above the purchase: a sentence that will never be run costs no run.
                approved = await _classify_edit(
                    conn, request, values, generator, caller
                )
            if request.action == "accept":
                # After the free refusals above, so a run that was never resumable
                # costs nothing, and inside the lock, so simultaneous accepts
                # cannot each pass a cap neither has yet recorded.
                await _buy_panel(conn, caller)
            state = await _run_graph(
                graph,
                Command(
                    resume=GateDecision(
                        action=request.action,
                        query=_edited(request, values),
                        variants=(
                            {"a": request.headline_a, "b": request.headline_b}
                            if request.headline_a is not None
                            and request.headline_b is not None
                            else None
                        ),
                        instruction=approved or request.instruction,
                    ).model_dump()
                ),
                request.thread_id,
            )
        return await _kept(
            _outcome(
                state,
                thread_id=request.thread_id,
                variants=values["variants"],
                credit=credit,
            ),
            conn=conn,
            state=state,
            caller=caller,
        )


def _checkpoint_owner(checkpoint: Mapping[str, Any]) -> str | None:
    """The `owner` a thread's state carries, straight off its checkpoint.

    Every /evaluate thread sets it in its initial state; a /chat thread's
    state has no such channel, so this returns None there — and None matches
    no caller, which is exactly the refusal a chat id deserves from a run
    endpoint."""
    channels = checkpoint.get("channel_values", {})
    owner = channels.get("owner")
    return owner if isinstance(owner, str) else None


class RunProgress(BaseModel):
    """How many votes the run has bought so far — the waiting screen's number."""

    votes_recorded: int


@app.get("/evaluate/{thread_id}/progress")
async def evaluate_progress(
    thread_id: str,
    caller: str = Depends(caller_id),
    conn: psycopg.AsyncConnection = Depends(get_conn),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
) -> RunProgress:
    """The count behind the waiting screen (021/#126): votes are persisted per
    chunk (010e's crash-safety), so this reads live progress off rows the vote
    loop was already writing — no second channel, nothing streamed.

    - **The owner's alone**, by the resume's own rule: the count would confirm
      a guessed id, so anyone but the caller who started the run gets the same
      404 an unknown id gets.
    - **Read straight off the checkpoint**, not through the graph: ownership
      needs one state value, and building the graph would drag the panel model
      in as a dependency of a read that never votes.
    - **May undercount, never invents**: a cached vote keeps the stamp of the
      run that paid for it, so a repeat served from the ledger counts zero —
      accepted when the poll was settled on the ticket (2026-09-01).
    """
    checkpoint = await checkpointer.aget({"configurable": {"thread_id": thread_id}})
    if checkpoint is None or _checkpoint_owner(checkpoint) != caller:
        raise HTTPException(
            status_code=404, detail="no run is waiting for you on that id"
        )
    async with conn.cursor() as cur:
        await cur.execute("SELECT count(*) FROM votes WHERE test_id = %s", (thread_id,))
        row = await cur.fetchone()
    # A poll every few seconds must not hold its read transaction open.
    await conn.rollback()
    return RunProgress(votes_recorded=int(row[0]) if row else 0)


class ClosingStreamingResponse(StreamingResponse):
    """A StreamingResponse that closes its generator when the reader is gone.

    Neither Starlette layer does: on a disconnect the stream task is cancelled
    or its send raises, and the body generator is abandoned suspended at its
    yield — nothing ever calls `aclose()` on it (starlette 1.3.1,
    `StreamingResponse.__call__` and `BaseHTTPMiddleware._StreamingResponse`).
    "Collected eventually, at GC" never arrives either, because the abandoned
    run's model task is a live asyncio task, and live tasks anchor the whole
    graph against collection — measured in 113/#243: not at unwind, not after
    an explicit gc.collect(). So the run kept calling the model with no reader,
    which is exactly what `stream_analyst`'s `async with` was added to end.

    The close is shielded because there are two doors out of a disconnect and
    one of them is a cancellation: `BaseHTTPMiddleware` cancels the task
    running this response when the outer send's failure propagates, and an
    unshielded await here would be re-cancelled mid-cleanup, aborting the
    run's shutdown halfway through.
    """

    def __init__(
        self, content: AsyncGenerator[str, None], *, thread_id: str, **kwargs: Any
    ) -> None:
        super().__init__(content, **kwargs)
        self.thread_id = thread_id
        # Starlette keeps the same object as `body_iterator`, typed as a bare
        # iterable; this name keeps the generator's `aclose`.
        self._stream = content

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # The bind lives here, not in the endpoint: the body is produced after
        # the endpoint has returned, and this call is the whole of the send.
        with bind_thread(self.thread_id):
            try:
                await super().__call__(scope, receive, send)
            finally:
                with anyio.CancelScope(shield=True):
                    await self._stream.aclose()


async def preflight_chat(
    request: ChatRequest,
    _caller: str = Depends(caller_id),
    guard: ChatGuard | None = Depends(get_chat_guard),
) -> None:
    """Declared above `enforce_turn_limit` in the handler so it runs first:
    a refused message is refused above the charge and costs nothing. Behind
    `caller_id`, so an unsigned request is a 401 before it costs a classifier
    call — otherwise the door to the vendor's quota, and a pass/refuse oracle,
    would stand open to anyone. The caps still sit below: a signed-in caller
    past their turn limit is scored, then refused."""
    try:
        await guard_chat_message(
            guard,
            request.message,
            threshold=settings.chat_guard_threshold,
            content=settings.chat_content_categories,
        )
    except (BlockedMessage, ContentRefused) as error:
        # 400, not 422: the message is well-formed; what it says was refused.
        raise HTTPException(status_code=400, detail=str(error)) from error


async def load_chat_report(
    request: ChatRequest,
    caller: str = Depends(caller_id),
    conn: psycopg.AsyncConnection = Depends(get_conn),
) -> EvaluateResponse:
    """The test this turn is about, from the server's own copy (035/#136).

    Loaded under the signed-in subject in the query itself, so the analyst's
    scope — which votes, which personas its tools may reach — is what the run
    wrote and nothing the caller posted. Kept or not: the run the rail refused
    is still on the reader's screen, and its analyst reads the unkept row.
    Declared first in the handler, above the pre-flight and the charge: a
    missing or foreign test is the tests endpoint's own 404, settled by one
    free read, before a classifier call or a ledger row.
    """
    report = await load_report(conn, test_id=request.test_id, owner=caller)
    if report is None:
        raise HTTPException(status_code=404, detail="no such test")
    return EvaluateResponse.model_validate(report)


@app.post("/chat")
async def chat(
    request: ChatRequest,
    report: EvaluateResponse = Depends(load_chat_report),
    _preflight: None = Depends(preflight_chat),
    _limit: None = Depends(enforce_turn_limit),
    caller: str = Depends(caller_id),
    analyst: BaseChatModel = Depends(get_analyst),
    conn: psycopg.AsyncConnection = Depends(get_conn),
    embedder: Embedder = Depends(get_embedder),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
) -> StreamingResponse:
    # No translator and no panel model: with `run_panel_test` gone, this
    # endpoint has nothing that could buy a vote. The absence is the guarantee —
    # a spend path cannot be reintroduced here without a visible new dependency.
    # The report is the server's own, so its tally needs no guarding here;
    # every failure from here on is the stream's to report, as an in-band
    # `error` event with a fixed sentence (see stream_analyst).
    # Autocommit from here on: the stream's tools are this connection's only
    # remaining users, every one of them reads, and langgraph runs a turn's
    # tool calls concurrently on it (`ToolNode._afunc` gathers them).
    # Non-autocommit, those reads shared one transaction nothing ever closed —
    # the connection sat idle-in-transaction from the first tool to the end of
    # the request (the state pooler reapers and
    # `idle_in_transaction_session_timeout` kill, and the ACCESS SHARE holder
    # a deploy's DDL queues behind), and one failing statement poisoned the
    # transaction for any sibling in the same gather (113/#243). Autocommit
    # makes the shared transaction not exist, rather than shorter-lived. The
    # turn charge is unaffected: `_charge_ledger` committed before this line,
    # inside `enforce_turn_limit`. And the switch is its own guard — psycopg
    # refuses it inside a transaction, so a future dependency that leaves one
    # open on this connection fails loudly here, not by silently sharing it.
    await conn.set_autocommit(True)
    return ClosingStreamingResponse(
        stream_analyst(
            model=analyst,
            result=report,
            owner=caller,
            thread_id=request.thread_id,
            message=request.message,
            checkpointer=checkpointer,
            deps=ToolDeps(conn=conn, embedder=embedder),
        ),
        thread_id=request.thread_id,
        media_type="application/x-ndjson",
    )
