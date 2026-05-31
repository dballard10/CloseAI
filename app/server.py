"""FastAPI server exposing the CloseAI pipeline + a single-page demo UI.

Run:
    uvicorn app.server:app --reload --port 8000
Then open http://localhost:8000
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from closeai.config import Settings
from closeai.llm_client import ModelProviderError, provider_is_configured
from closeai.pipeline import CloseAIPipeline
from closeai.private_consult import PrivateConsultPipeline
from closeai.schemas import CheckerResult, ConsultMode, SensitiveEntity, UtilityResult

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
_consult_pipeline = PrivateConsultPipeline()

_STATIC = Path(__file__).parent / "static"
_SESSION_TTL_SECONDS = 60 * 60


@dataclass
class ApprovalSession:
    raw_prompt: str
    mode: ConsultMode
    classified_prompt: str
    detected_entities: list[SensitiveEntity]
    checker_result: CheckerResult
    utility_result: UtilityResult
    created_at: float
    updated_at: float


class DeidentifyRequest(BaseModel):
    text: str


class QueryRequest(BaseModel):
    text: str
    system: str | None = None
    provider: str | None = None
    model: str | None = None


class ClassifyRequest(BaseModel):
    text: str
    mode: ConsultMode = "general"


class ReviseClassificationRequest(BaseModel):
    session_id: str
    feedback: str


class ApproveAndQueryRequest(BaseModel):
    session_id: str
    approved_prompt: str | None = None
    system: str | None = None
    provider: str | None = None
    model: str | None = None


_approval_sessions: dict[str, ApprovalSession] = {}


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


def _prune_sessions(now: float | None = None) -> None:
    current = now or time.time()
    expired = [
        session_id
        for session_id, session in _approval_sessions.items()
        if current - session.updated_at > _SESSION_TTL_SECONDS
    ]
    for session_id in expired:
        _approval_sessions.pop(session_id, None)


def _session_or_error(session_id: str) -> ApprovalSession | JSONResponse:
    _prune_sessions()
    session = _approval_sessions.get(session_id)
    if session is None:
        return JSONResponse(
            status_code=404,
            content={
                "ok": False,
                "error": {
                    "message": "That approval session expired or does not exist. Please classify the prompt again."
                },
            },
        )
    return session


def _draft_payload(session_id: str, session: ApprovalSession, repaired: bool = False) -> dict:
    return {
        "ok": True,
        "session_id": session_id,
        "mode": session.mode,
        "classified_prompt": session.classified_prompt,
        "detected_entities": [entity.model_dump() for entity in session.detected_entities],
        "checker_result": session.checker_result.model_dump(),
        "utility_result": session.utility_result.model_dump(),
        "external_call_allowed": (
            session.checker_result.passed
            and session.utility_result.utilityScore >= _consult_pipeline.utility_threshold
        ),
        "repaired": repaired,
        "model_status": _consult_pipeline.model_status,
    }


def _create_or_update_session(
    *,
    raw_prompt: str,
    mode: ConsultMode,
    classified_prompt: str,
    detected_entities: list[SensitiveEntity],
    checker_result: CheckerResult,
    utility_result: UtilityResult,
    session_id: str | None = None,
) -> tuple[str, ApprovalSession]:
    now = time.time()
    resolved_session_id = session_id or uuid4().hex
    existing = _approval_sessions.get(resolved_session_id)
    session = ApprovalSession(
        raw_prompt=raw_prompt,
        mode=mode,
        classified_prompt=classified_prompt,
        detected_entities=detected_entities,
        checker_result=checker_result,
        utility_result=utility_result,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    _approval_sessions[resolved_session_id] = session
    return resolved_session_id, session


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
        "approval_model_status": _consult_pipeline.model_status,
    }


@app.post("/api/deidentify")
def deidentify(req: DeidentifyRequest) -> dict:
    result = _pipeline.deidentify(req.text)
    return result.model_dump()


@app.post("/api/classify")
def classify(req: ClassifyRequest):
    classified, entities, checker, utility, repaired = _consult_pipeline.prepare_classified_prompt(
        req.text,
        req.mode,
    )
    session_id, session = _create_or_update_session(
        raw_prompt=req.text,
        mode=req.mode,
        classified_prompt=classified,
        detected_entities=entities,
        checker_result=checker,
        utility_result=utility,
    )
    return _draft_payload(session_id, session, repaired=repaired)


@app.post("/api/revise-classification")
def revise_classification(req: ReviseClassificationRequest):
    session = _session_or_error(req.session_id)
    if isinstance(session, JSONResponse):
        return session

    classified, entities, checker, utility, repaired = _consult_pipeline.prepare_classified_prompt(
        session.raw_prompt,
        session.mode,
        feedback=req.feedback,
        previous_sanitized=session.classified_prompt,
    )
    session_id, updated = _create_or_update_session(
        raw_prompt=session.raw_prompt,
        mode=session.mode,
        classified_prompt=classified,
        detected_entities=entities,
        checker_result=checker,
        utility_result=utility,
        session_id=req.session_id,
    )
    return _draft_payload(session_id, updated, repaired=repaired)


@app.post("/api/approve-and-query")
def approve_and_query(req: ApproveAndQueryRequest):
    session = _session_or_error(req.session_id)
    if isinstance(session, JSONResponse):
        return session

    approved_prompt = (req.approved_prompt or session.classified_prompt).strip()
    checker, utility = _consult_pipeline._check_for_approval(
        session.raw_prompt,
        approved_prompt,
        session.detected_entities,
        [],
        session.mode,
    )
    if not checker.passed:
        session.checker_result = checker
        session.utility_result = utility
        session.updated_at = time.time()
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": {
                    "message": "The approved prompt still appears to contain private details. Revise it before sending."
                },
                "session_id": req.session_id,
                "classified_prompt": approved_prompt,
                "checker_result": checker.model_dump(),
                "utility_result": utility.model_dump(),
            },
        )

    provider = req.provider or _settings.provider
    client = _pipeline.model_client(provider=provider, model=req.model)
    try:
        response = client.complete(approved_prompt, system=req.system)
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
                "session_id": req.session_id,
                "classified_prompt": approved_prompt,
                "checker_result": checker.model_dump(),
                "utility_result": utility.model_dump(),
            },
        )

    _approval_sessions.pop(req.session_id, None)
    return {
        "ok": True,
        "session_id": req.session_id,
        "classified_prompt": approved_prompt,
        "model_response": response,
        "checker_result": checker.model_dump(),
        "utility_result": utility.model_dump(),
        "provider": provider,
        "model": req.model or _settings.model,
    }


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
