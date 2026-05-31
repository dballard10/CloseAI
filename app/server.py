"""FastAPI server exposing the CloseAI pipeline + a single-page demo UI.

Run:
    uvicorn app.server:app --reload --port 8000
Then open http://localhost:8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from closeai.config import Settings
from closeai.llm_client import ModelProviderError, provider_is_configured
from closeai.pipeline import CloseAIPipeline

app = FastAPI(title="CloseAI", description="De-identifying proxy for closed LLMs")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def setup_hint(provider: str) -> str | None:
    provider = provider.lower()
    if provider == "openai":
        return (
            "Add OPENAI_API_KEY=... to .env, then restart `just dev`. "
            "For an offline smoke test, set CLOSEAI_PROVIDER=echo."
        )
    if provider == "anthropic":
        return (
            "Add ANTHROPIC_API_KEY=... to .env, then restart `just dev`. "
            "For an offline smoke test, set CLOSEAI_PROVIDER=echo."
        )
    if provider == "wandb":
        return (
            "Add WANDB_API_KEY=... to .env, then restart `just dev`. "
            "For an offline smoke test, set CLOSEAI_PROVIDER=echo."
        )
    if provider == "ollama":
        return "Start Ollama with `ollama serve` and pull a model such as `ollama pull llama3.2`."
    return None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    configured = provider_is_configured(_settings.provider)
    return {
        "status": "ok",
        "presidio_mode": _pipeline.presidio.mode,
        "llm_detector_enabled": _pipeline.llm_detector.enabled,
        "provider": _settings.provider,
        "model": _settings.model,
        "provider_configured": configured,
        "setup_message": None if configured else setup_hint(_settings.provider),
        "trace_raw": _settings.trace_raw,
    }


@app.post("/api/deidentify")
def deidentify(req: DeidentifyRequest) -> dict:
    result = _pipeline.deidentify(req.text)
    return result.model_dump()


@app.post("/api/query")
def query(req: QueryRequest):
    mask_result = _pipeline.deidentify(req.text)
    client = _pipeline.model_client(provider=req.provider, model=req.model)
    try:
        raw_response = client.complete(mask_result.masked_text, system=req.system)
    except ModelProviderError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "ok": False,
                "error": {
                    "provider": exc.provider,
                    "message": exc.message,
                    "setup_hint": setup_hint(exc.provider),
                },
                "masked_prompt": mask_result.masked_text,
                "mask_result": mask_result.model_dump(),
            },
        )

    result = _pipeline.build_result(req.text, mask_result, raw_response)
    return result.model_dump()
