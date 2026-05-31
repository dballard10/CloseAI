"""FastAPI server exposing the ClosedAI privacy-gate pipeline.

Run:
    uvicorn app.server:app --reload --port 8000
Then point the Next.js API layer at http://localhost:8000/run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from closeai.config import Settings
from closeai.pipeline import CloseAIPipeline
from closeai.private_consult import PrivateConsultPipeline
from closeai.schemas import ConsultMode, RunRequest

app = FastAPI(title="ClosedAI", description="Evaluated privacy gate for external LLM consultation")

_settings = Settings()
_consult_pipeline = PrivateConsultPipeline()
_legacy_pipeline: CloseAIPipeline | None = None


def _get_legacy_pipeline() -> CloseAIPipeline:
    global _legacy_pipeline
    if _legacy_pipeline is None:
        _legacy_pipeline = CloseAIPipeline(settings=_settings)
    return _legacy_pipeline

_STATIC = Path(__file__).parent / "static"


class DeidentifyRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    text: str
    system: str | None = None
    provider: str | None = None
    model: str | None = None


class LegacyRunRequest(BaseModel):
    rawPrompt: str
    mode: ConsultMode = "general"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "product": "ClosedAI",
        "python_pipeline": "ready",
        "consult_pipeline": _consult_pipeline.model_status,
        "internal_provider": _consult_pipeline.internal_provider,
        "external_provider": _consult_pipeline.external_provider,
        "provider": _settings.provider,
        "model": _settings.model,
    }


@app.post("/run")
def run(req: RunRequest) -> dict:
    result = _consult_pipeline.run(req.rawPrompt, req.mode)
    return result.model_dump()


@app.post("/run/stream")
def run_stream(req: RunRequest) -> StreamingResponse:
    def events() -> Iterator[str]:
        for event in _consult_pipeline.run_stream(req.rawPrompt, req.mode):
            yield json.dumps(event) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/api/run")
def api_run(req: LegacyRunRequest) -> dict:
    result = _consult_pipeline.run(req.rawPrompt, req.mode)
    return result.model_dump()


@app.post("/api/deidentify")
def deidentify(req: DeidentifyRequest) -> dict:
    result = _get_legacy_pipeline().deidentify(req.text)
    return result.model_dump()


@app.post("/api/query")
def query(req: QueryRequest) -> dict:
    # Allow per-request provider/model override without rebuilding detectors.
    _pipeline = _get_legacy_pipeline()
    if req.provider:
        _pipeline.model.provider = req.provider
    if req.model:
        _pipeline.model.model = req.model
    result = _pipeline.deidentify_and_query(req.text, system=req.system)
    return result.model_dump()
