from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import check_connection
from app.llm import OpenRouterPanelLLM
from app.panel import FIXED_PANEL
from app.schemas import EvaluateRequest, EvaluateResponse
from app.vote import PanelLLM, collect_panel_votes
from app.verdict import tally_votes

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
    verdict = tally_votes(votes, variant_ids=list(variants))
    return EvaluateResponse(verdict=verdict, variants=variants, votes=votes)
