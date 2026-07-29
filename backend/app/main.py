import logging
from collections.abc import Iterator

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import USD_PER_VOTE, settings
from app.db import check_connection
from app.llm import OpenRouterPanelLLM, OpenRouterTargetTranslator, remaining_credit
from app.panel import votes_with_voters
from app.pipeline import EmptyPanel, NoVotes, run_panel_test
from app.schemas import EvaluateRequest, EvaluateResponse, Notice
from app.targeting import TargetTranslator
from app.vote import OutOfCredit, PanelLLM

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
        model=settings.panel.model,
    )


def get_translator() -> TargetTranslator:
    return OpenRouterTargetTranslator(
        api_key=_require_api_key(),
        base_url=settings.openrouter_base_url,
        model=settings.targeting_model,
    )


def get_remaining_credit() -> float | None:
    if settings.openrouter_api_key is None:
        return None
    return remaining_credit(
        api_key=settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
    )


def budget_notice(remaining: float | None, *, size: int) -> tuple[Notice, ...]:
    """Warn-and-proceed, never refuse (010f's decision): a run the credit cannot
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
    """One plain connection per request — no pool, no pgvector adapter.

    The panel path reads scalar columns only (017 dropped the persona vector from
    targeting), so `register_vector` is the write path's and 012's concern, not
    this one's.
    """
    with psycopg.connect(settings.database_url) as conn:
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
) -> EvaluateResponse:
    variants = {"a": request.headline_a, "b": request.headline_b}
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
