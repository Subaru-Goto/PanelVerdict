import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import check_connection
from app.llm import OpenRouterPanelLLM
from app.panel import FIXED_PANEL
from app.schemas import EvaluateRequest, EvaluateResponse
from app.vote import PanelLLM, collect_panel_votes
from app.verdict import panel_verdict, tally_votes

logger = logging.getLogger(__name__)

app = FastAPI(title="PanelVerdict API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def get_panel_llm() -> PanelLLM:
    key = settings.openrouter_api_key
    if key is None:
        raise HTTPException(status_code=503, detail="OPENROUTER_API_KEY is not set")
    return OpenRouterPanelLLM(
        api_key=key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        model=settings.panel_model,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db": "up" if check_connection() else "down"}


@app.post("/evaluate")
def evaluate(
    request: EvaluateRequest, llm: PanelLLM = Depends(get_panel_llm)
) -> EvaluateResponse:
    variants = {"a": request.headline_a, "b": request.headline_b}
    votes = collect_panel_votes(
        test_id="tracer", variants=variants, panel=FIXED_PANEL, llm=llm
    )
    # Any failure is refused rather than reported, because this endpoint votes the
    # 5-persona FIXED_PANEL: one missing vote is a fifth of it, and a verdict on four
    # personas presented as a verdict on five is a half-panel. A 200-persona panel can
    # absorb a few and wants a partial-run policy instead — which is also why
    # `EvaluateResponse` has nowhere to put a shortfall.
    #
    # The detail names the exception types only. A failure message can carry provider
    # response text and the model's own output, which do not belong in an HTTP body.
    if votes.failures:
        logger.error("panel votes failed: %s", votes.failures)
        raise HTTPException(
            status_code=502,
            detail=(
                f"{len(votes.failures)} of {len(FIXED_PANEL)} panelists did not vote "
                f"({', '.join(sorted({f.error.split(':')[0] for f in votes.failures}))})"
            ),
        )
    tally = tally_votes(votes.records, variant_ids=list(variants))
    return EvaluateResponse(
        verdict=panel_verdict(preferring_b=tally.counts["b"], total=tally.total),
        tally=tally,
        variants=variants,
        votes=votes.records,
    )
