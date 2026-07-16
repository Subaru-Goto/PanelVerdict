from fastapi import FastAPI

from app.db import check_connection

app = FastAPI(title="PanelVerdict API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "db": "up" if check_connection() else "down"}
