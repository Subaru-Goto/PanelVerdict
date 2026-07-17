from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import check_connection
from app.config import settings

app = FastAPI(title="PanelVerdict API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db": "up" if check_connection() else "down"}
