"""FastAPI server exposing the CloseAI pipeline + a single-page demo UI.

Run:
    uvicorn app.server:app --reload --port 8000
Then open http://localhost:8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from closeai.config import Settings
from closeai.pipeline import CloseAIPipeline

app = FastAPI(title="CloseAI", description="De-identifying proxy for closed LLMs")

# One pipeline instance reused across requests (loads spaCy/Presidio once).
_settings = Settings()
_pipeline = CloseAIPipeline(settings=_settings)

_STATIC = Path(__file__).parent / "static"


class DeidentifyRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    text: str
    system: str | None = None
    provider: str | None = None
    model: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "presidio_mode": _pipeline.presidio.mode,
        "llm_detector_enabled": _pipeline.llm_detector.enabled,
        "provider": _settings.provider,
        "model": _settings.model,
    }


@app.post("/api/deidentify")
def deidentify(req: DeidentifyRequest) -> dict:
    result = _pipeline.deidentify(req.text)
    return result.model_dump()


@app.post("/api/query")
def query(req: QueryRequest) -> dict:
    # Allow per-request provider/model override without rebuilding detectors.
    if req.provider:
        _pipeline.model.provider = req.provider
    if req.model:
        _pipeline.model.model = req.model
    result = _pipeline.deidentify_and_query(req.text, system=req.system)
    return result.model_dump()
