import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, NamedTuple
from uuid import uuid4

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from app.analyst import ToolDeps, analysis_facts, stream_analyst
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
from app.db import check_connection
from app.graph import GateDecision, PanelPreview, build_evaluate_graph
from app.llm import (
    OpenRouterEmbedder,
    OpenRouterPanelLLM,
    OpenRouterRolePlayGenerator,
    analyst_chat_model,
    remaining_credit,
)
from app.panel import votes_with_voters
from app.persistence import (
    adeny_data_api,
    delete_report,
    delete_reports_of,
    list_reports,
    load_report,
    store_report,
)
from app.pipeline import EmptyPanel, NoVotes
from app.roleplay import RolePlayGenerator, RolePlayRefused
from app.schemas import (
    ChatRequest,
    EvaluateRequest,
    EvaluateResponse,
    Locale,
    Notice,
    PanelEdit,
    PanelVerdict,
    ResumeRequest,
    TargetQuery,
    VoteTally,
)
from app.screening import OpenRouterScreener, Screener, UnsafeInput
from app.tracing import configure_tracing
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
    async with AsyncConnectionPool(
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
        yield


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
_GUARDED_PATHS = ("/evaluate", "/chat", "/me")


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


async def get_conn() -> AsyncIterator[psycopg.AsyncConnection]:
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
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await register_vector_async(conn)
        yield conn


# The ledger's day, written once, because four things read it: the cap, the
# sweep, the remaining-runs figure `/me` reports, and how long a paused run may
# be redeemed for. Two literals would let any of them drift from the others.
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
        # A turn's cost is unmeasured; the pool charges the measured ceiling
        # A turn's real cost is unmeasured; USD_PER_TURN explains the stand-in.
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
    return {"runs_per_day": limit, "runs_remaining": max(0, limit - used)}


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
    await delete_reports_of(conn, owner=caller)
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


@app.get("/tests")
async def my_tests(
    conn: psycopg.AsyncConnection = Depends(get_conn),
    caller: str = Depends(caller_id),
) -> list[StoredTest]:
    """This account's finished tests, newest first."""
    return [
        StoredTest.model_validate(row) for row in await list_reports(conn, owner=caller)
    ]


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
    """A finished run. `status` is additive — every older field is still here."""

    status: Literal["complete"] = "complete"


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
    # lines it wrote here can be paired. The vote loop logs a different id
    # (`panel usage test_id=...`); unifying the two is a separate job.
    logger.info(
        "evaluate thread_id=%s: %s",
        thread_id,
        "paused at the panel gate" if paused else "complete",
    )
    if paused:
        return PausedRun(
            thread_id=thread_id, preview=PanelPreview.model_validate(paused[0].value)
        )
    result = state["result"]
    return CompletedRun(
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
    """Keep a finished report for the account that ran it (117/#252).

    **Best-effort, and never fails the response.** When this runs the votes are
    already bought, so a raised write would lose the report *and* the run —
    which is 049/#147's own complaint arriving through the mechanism meant to
    answer it. The customer holds the report in the body either way; what a
    failure costs is the copy, and that is the cheaper loss by a whole run.

    A paused run is not kept: it has bought nothing and has no verdict.

    `status` is excluded because it belongs to the HTTP answer rather than to
    the record — a row carrying it would be a stored response, not a stored
    test.
    """
    if not isinstance(outcome, CompletedRun):
        return outcome
    test_id = state["result"].test_id
    try:
        await store_report(
            conn,
            test_id=test_id,
            owner=caller,
            report=outcome.model_dump(mode="json", exclude={"status"}),
        )
    except Exception:
        # Logged with the id so the loss is traceable to a run, and swallowed on
        # purpose — see the docstring.
        logger.exception("could not keep the report for test_id=%s", test_id)
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
    except NoVotes as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except OutOfCredit as error:
        raise HTTPException(status_code=402, detail=str(error)) from error


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
    if request.reading_accepted:
        await _refuse_if_run_capped(conn, caller)
    instruction = await _approved_on_entry(conn, request, generator, caller)
    if request.reading_accepted:
        await _buy_panel(conn, caller)
    variants = {"a": request.headline_a, "b": request.headline_b}
    thread_id = str(uuid4())
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
    state = await _run_graph(
        graph,
        {
            "query": _settled_query(request.target),
            "notices": [
                Notice(
                    severity="reading",
                    message=(
                        "No control narrowed the panel, so it is a "
                        "cross-section of the whole pool rather than a match "
                        "to anyone in particular."
                    ),
                )
            ]
            if untargeted
            else [],
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
                "could not release the resume lock for %s (%s); the connection"
                " close will release it",
                thread_id,
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
    checked = await asyncio.to_thread(generator.check, instruction=sentence)
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


def _settled_query(edit: PanelEdit) -> TargetQuery:
    """Controls → the reading, verbatim. Both doors pass through here — the
    form's controls and the gate's edit — so what runs is always exactly what a
    human set.

    `coverage` is `requested` by definition: a control cannot be misread, so
    there is no ladder to report. `notices` start empty for the same reason —
    they existed to explain how free text was interpreted, and nothing is
    interpreted any more. `traits` are always empty: temperament left targeting
    when the controls arrived (094).

    `countries` is the one control whose blank needs translating: TargetQuery
    keeps countries explicit — empty means *no* country and matches nobody —
    while an untouched control means the caller didn't care. Every place, said
    outright.
    """
    return TargetQuery(
        **edit.model_dump() | {"countries": edit.countries or list(Locale)},
        traits=[],
        coverage="requested",
        notices=[],
    )


def _edited(request: ResumeRequest, values: dict) -> TargetQuery | None:
    """The edited reading, when the gate's answer carries one."""
    if request.query is None:
        return None
    return _settled_query(request.query)


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
            approved = await _classify_edit(conn, request, values, generator, caller)
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


@app.post("/chat")
async def chat(
    request: ChatRequest,
    _limit: None = Depends(enforce_turn_limit),
    analyst: BaseChatModel = Depends(get_analyst),
    conn: psycopg.AsyncConnection = Depends(get_conn),
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
