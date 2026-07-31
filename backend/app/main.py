import logging
from collections.abc import Iterator

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pgvector.psycopg import register_vector

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

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
from app.screening import OpenRouterScreener, Screener, UnsafeInput, screen_inputs
from app.schemas import (
    ChatRequest,
    EvaluateRequest,
    EvaluateResponse,
    Notice,
)
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

app = FastAPI(title="PanelVerdict API")

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db": "up" if check_connection() else "down"}


@app.post("/evaluate")
def evaluate(
    request: EvaluateRequest,
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


# One saver for the process lifetime — threads must outlive requests, which is
# the whole point of a checkpointer. In-memory: a restart forgets every thread,
# accepted at v1 demo scale (the report the chat is scoped to lives client-side).
_CHECKPOINTER = InMemorySaver()


@app.post("/chat")
def chat(
    request: ChatRequest,
    analyst: BaseChatModel = Depends(get_analyst),
    conn: psycopg.Connection = Depends(get_conn),
    embedder: Embedder = Depends(get_embedder),
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
            checkpointer=_CHECKPOINTER,
            deps=ToolDeps(conn=conn, embedder=embedder),
        ),
        media_type="application/x-ndjson",
    )
