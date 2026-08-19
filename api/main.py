"""FastAPI server for the SAP consultant."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rag.config.settings import AppSettings
from rag.consultant import SAPConsultant

ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"

app = FastAPI(title="AI SAP Consultant", version="1.0.0")
settings = AppSettings.from_env()
consultant = SAPConsultant(settings=settings)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1)
    session_id: str | None = None
    filters: dict[str, str] | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)


class ChatResponse(BaseModel):
    session_id: str
    query: str
    answer: str
    sources: list[dict[str, Any]]
    context_size: int = 0
    model: str | None = None
    history_length: int = 0
    execution_time_seconds: float | None = None
    error: str | None = None
    intent: str | None = None
    phase: str | None = None


def get_active_consultant(session_id: str | None) -> SAPConsultant:
    session = consultant.session_store.get_or_create(
        session_id=session_id,
        max_turns=settings.max_history_turns,
    )
    return SAPConsultant(
        settings=settings,
        session_store=consultant.session_store,
        diagnosis_store=consultant.diagnosis_store,
        diagnosis_manager=consultant.diagnosis_manager,
        memory=session,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    active = get_active_consultant(request.session_id)
    payload = active.ask(
        query=request.query,
        filters=request.filters,
        top_k=request.top_k,
    )

    if payload.get("error") and not payload.get("answer"):
        raise HTTPException(status_code=400, detail=payload["error"])

    return ChatResponse(**{k: v for k, v in payload.items() if k in ChatResponse.model_fields})


@app.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    active = get_active_consultant(request.session_id)

    def event_stream():
        for event in active.ask_stream(
            query=request.query,
            filters=request.filters,
            top_k=request.top_k,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/sessions/{session_id}/reset")
def reset_session(session_id: str) -> dict[str, str]:
    cleared = consultant.session_store.clear(session_id)
    consultant.diagnosis_manager.clear_session(session_id)
    if not cleared:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "reset", "session_id": session_id}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    deleted = consultant.session_store.delete(session_id)
    consultant.diagnosis_manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
