import hmac
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
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
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
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
    USD_PER_PREVIEW,
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
    OpenRouterTargetTranslator,
    analyst_chat_model,
    remaining_credit,
)
from app.panel import votes_with_voters
from app.persistence import deny_data_api
from app.pipeline import EmptyPanel, NoVotes
from app.roleplay import RolePlayGenerator, RolePlayRefused
from app.schemas import (
    ChatRequest,
    EvaluateRequest,
    EvaluateResponse,
    Notice,
    ResumeRequest,
    TargetQuery,
)
from app.screening import OpenRouterScreener, Screener, UnsafeInput
from app.targeting import TargetTranslator
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
        # After setup(), not before: the sweep must reach the tables the
        # library just created, which hold analyst transcripts and would
        # otherwise sit readable over the project's Data API — a surface this
        # release opens by shipping a publishable key to the browser
        # (063/#158).
        with pool.connection() as conn:
            deny_data_api(conn)
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


def get_translator() -> TargetTranslator:
    """Translate target description into structured output for the panel"""
    return OpenRouterTargetTranslator(
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


def enforce_evaluate_limits(
    request: EvaluateRequest,
    caller: str = Depends(caller_id),
    conn: psycopg.Connection = Depends(get_conn),
) -> None:
    """Charge for the preview, and the panel too when there is no gate.

    Two purchases, counted separately: a preview buys the two model calls a run
    makes before the gate, a panel buys every vote it is sized to.
    `/evaluate/resume` charges the panel when a reader accepts; this charges it
    up front only for a run told the reading is already approved, which never
    stops to ask.

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
    # A preview buys model calls, not a panel: the graph stops at the gate before
    # any vote is cast. Two calls for a demographics-only run — one translation
    # and one screening — and a third when the reader wrote audience words, which
    # have to be rewritten into the sentence the gate offers for approval.
    charges = [
        _Charge(_PREVIEW, caller, settings.evaluate_previews_per_day, "previews")
    ]
    # Two written figures summed in Decimal, never one computed float: `_usd`
    # takes written figures only, for the reason its docstring gives.
    preview_usd = _usd(USD_PER_PREVIEW)
    if request.audience.strip():
        preview_usd += _usd(USD_PER_ROLEPLAY)
    spend = _Spend(_PREVIEW, preview_usd)
    if request.reading_accepted:
        # No gate on this run, so there is no accept to charge later. One call
        # for both halves, so a caller already at their run cap is not charged
        # for a preview the refusal means never happens.
        charge, price = _panel_purchase(caller)
        charges.append(charge)
        spend = _Spend(_EVALUATE, preview_usd + price)
    _charge_ledger(conn, *charges, spend=spend)


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


def _charge_ledger(
    conn: psycopg.Connection, *charges: _Charge, spend: _Spend | None = None
) -> None:
    """Enforce every cap, then record one attempt against each — or refuse.

    Count-then-insert is not a limit under load: READ COMMITTED cannot see
    another transaction's uncommitted rows and sync handlers run in a thread
    pool, so simultaneous requests all read the same count and all pass — 10
    concurrent requests took 7 slots out of a limit of 3, measured. Advisory
    locks make the database arbitrate instead.

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
    with conn.cursor() as cur:
        if pooled is not None:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("spend-pool",))
        for charge in sorted(active):
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"{charge.endpoint}:{charge.key}",),
            )
        for charge in active:
            cur.execute(
                "DELETE FROM request_ledger WHERE endpoint = %s AND caller = %s"
                f" AND {_LEDGER_EXPIRED}",
                (charge.endpoint, charge.key),
            )
            cur.execute(
                "SELECT count(*) FROM request_ledger"
                f" WHERE endpoint = %s AND caller = %s AND {_LEDGER_WINDOW}",
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
        if pooled is not None:
            cur.execute(
                "DELETE FROM spend_ledger WHERE spent_at < now()"
                f" - interval '{LEDGER_HOURS} hours'"
            )
            cur.execute(
                "SELECT coalesce(sum(usd), 0) FROM spend_ledger"
                " WHERE spent_at > now() - interval '24 hours'"
            )
            row = cur.fetchone()
            spent = Decimal(row[0]) if row else Decimal(0)
            if spent + pooled.usd > cap:
                conn.rollback()
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
            cur.execute(
                "INSERT INTO request_ledger (endpoint, caller) VALUES (%s, %s)",
                (charge.endpoint, charge.key),
            )
        if pooled is not None:
            cur.execute(
                "INSERT INTO spend_ledger (endpoint, usd) VALUES (%s, %s)",
                (pooled.endpoint, pooled.usd),
            )
    conn.commit()


def tracing_enabled() -> bool:
    """Whether this process is really sending traces.

    A dependency so a test can report a traced deployment without turning
    tracing on for the test run.
    """
    return _TRACING


@app.get("/health")
def health(
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
        "db": "up" if check_connection() else "down",
        "auth": "off" if verifier is None else "on",
        # The form's disclosure line reads this. One deployment answers for
        # both, so the page cannot disagree with what is actually happening.
        "tracing": "on" if tracing else "off",
    }


@app.get("/me")
def me(
    caller: str = Depends(caller_id),
    conn: psycopg.Connection = Depends(get_conn),
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM request_ledger"
            f" WHERE endpoint = %s AND caller = %s AND {_LEDGER_WINDOW}",
            (_EVALUATE, caller),
        )
        row = cur.fetchone()
    used = int(row[0]) if row else 0
    return {"runs_per_day": limit, "runs_remaining": max(0, limit - used)}


@app.delete("/me", status_code=204)
def forget_me(
    caller: str = Depends(caller_id),
    deleter: AccountDeleter | None = Depends(get_account_deleter),
) -> Response:
    """Erase the account, on request (063/#158).

    Cheap, because the subject-id rule means there is nowhere else to look: the
    address lives in the provider's `auth.users` table and this call removes
    it. What stays behind is `request_ledger` rows holding an opaque id and a
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
        deleter.delete(caller)
    except DeletionFailed:
        raise HTTPException(
            status_code=502,
            detail="the account could not be deleted — nothing was changed",
        ) from None
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


def _run_graph(graph, payload, thread_id: str):
    """Run the graph and map its refusals to status codes.

    Every message forwarded here is this codebase's own: `EmptyPanel` is a fixed
    sentence and `NoVotes` carries exception type names only, never provider or
    model text.
    """
    try:
        return graph.invoke(
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
        # never echoed, and no panel was drawn — so this costs no run.
        raise HTTPException(status_code=422, detail=error.sentence) from error
    except NoVotes as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except OutOfCredit as error:
        raise HTTPException(status_code=402, detail=str(error)) from error


@app.post("/evaluate")
def evaluate(
    request: EvaluateRequest,
    _limit: None = Depends(enforce_evaluate_limits),
    caller: str = Depends(caller_id),
    llm: PanelLLM = Depends(get_panel_llm),
    translator: TargetTranslator = Depends(get_translator),
    conn: psycopg.Connection = Depends(get_conn),
    credit: float | None = Depends(get_remaining_credit),
    screener: Screener | None = Depends(get_screener),
    generator: RolePlayGenerator = Depends(get_generator),
    checkpointer: BaseCheckpointSaver = Depends(get_checkpointer),
) -> PausedRun | CompletedRun:
    """Start a run. Stops at the panel gate unless the reading was approved.

    The preview is charged here, because reaching the gate costs two model
    calls whether or not the reader goes on to buy. The panel is charged where
    it is bought — on accept, or here too when the reading arrives approved and
    there is no gate to stop at.
    """
    variants = {"a": request.headline_a, "b": request.headline_b}
    thread_id = str(uuid4())
    graph = build_evaluate_graph(
        conn=conn,
        translator=translator,
        llm=llm,
        screener=screener,
        generator=generator,
        checkpointer=checkpointer,
    )
    state = _run_graph(
        graph,
        {
            "description": request.target_description,
            "audience": request.audience,
            "variants": variants,
            "size": settings.panel.size,
            "reading_accepted": request.reading_accepted,
            "owner": caller,
            "started_at": _now().isoformat(),
        },
        thread_id,
    )
    return _outcome(state, thread_id=thread_id, variants=variants, credit=credit)


@contextmanager
def _only_one_answer(conn: psycopg.Connection, thread_id: str) -> Iterator[None]:
    """Hold a run while it is being answered, or refuse.

    A session lock, not a transaction lock: the vote loop commits per chunk, and
    a transaction lock would be released by the first of them.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s))", (f"resume:{thread_id}",)
        )
        row = cur.fetchone()
    if not (row and row[0]):
        raise HTTPException(
            status_code=409, detail="this run is already being answered"
        )
    try:
        yield
    finally:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_unlock(hashtext(%s))", (f"resume:{thread_id}",)
            )


def _check_price(request: ResumeRequest, values: dict) -> Decimal:
    """What classifying the reader's edited sentence costs the day's pool.

    Only a real edit is checked, so only a real edit is charged: restoring the
    model's own draft costs nothing, because its verdict was reached when it was
    written. A refused edit returns the reader to the gate, so edits can be made
    one after another — which is exactly why this is metered rather than trusted
    to be occasional.

    The per-caller bound on how many checks a day may hold is still owed (094):
    it needs a measurement of the call's real cost, and the pool bounds the day
    in the meantime.
    """
    edited = request.instruction
    if edited is None or not edited.strip() or edited == values.get("instruction", ""):
        return Decimal(0)
    return _usd(USD_PER_ROLEPLAY)


def _edited(request: ResumeRequest, values: dict) -> TargetQuery | None:
    """Build the edited reading from the filter fields a caller may set.

    `coverage` and `notices` are rebuilt here rather than taken from the caller.
    Coverage is `requested` because an explicit edit is, by definition, exactly
    what was asked for; the notices explained the *original words* and no longer
    describe this filter.
    """
    if request.query is None:
        return None
    return TargetQuery(**request.query.model_dump(), coverage="requested", notices=[])


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
def resume_evaluate(
    request: ResumeRequest,
    caller: str = Depends(caller_id),
    llm: PanelLLM = Depends(get_panel_llm),
    translator: TargetTranslator = Depends(get_translator),
    conn: psycopg.Connection = Depends(get_conn),
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
        translator=translator,
        llm=llm,
        screener=screener,
        generator=generator,
        checkpointer=checkpointer,
    )
    config = {"configurable": {"thread_id": request.thread_id}}
    with _only_one_answer(conn, request.thread_id):
        snapshot = graph.get_state(config)
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
        if request.action == "accept":
            # The moment a panel is actually bought. After the free refusals
            # above, so a run that was never resumable costs nothing, and
            # inside the lock, so simultaneous accepts cannot each pass a cap
            # neither has yet recorded.
            charge, price = _panel_purchase(caller)
            _charge_ledger(
                conn,
                charge,
                spend=_Spend(_EVALUATE, price + _check_price(request, values)),
            )
        state = _run_graph(
            graph,
            Command(
                resume=GateDecision(
                    action=request.action,
                    query=_edited(request, values),
                    instruction=request.instruction,
                ).model_dump()
            ),
            request.thread_id,
        )
    return _outcome(
        state,
        thread_id=request.thread_id,
        variants=values["variants"],
        credit=credit,
    )


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
