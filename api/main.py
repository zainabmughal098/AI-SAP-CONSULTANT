"""FastAPI server for the SAP consultant."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from rag.config.settings import AppSettings
from rag.consultant import SAPConsultant

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session = consultant.session_store.get_or_create(
        session_id=request.session_id,
        max_turns=settings.max_history_turns,
    )
    active = SAPConsultant(settings=settings, session_store=consultant.session_store, memory=session)

    payload = active.ask(
        query=request.query,
        filters=request.filters,
        top_k=request.top_k,
    )

    if payload.get("error") and not payload.get("answer"):
        raise HTTPException(status_code=400, detail=payload["error"])

    return ChatResponse(**payload)


@app.post("/sessions/{session_id}/reset")
def reset_session(session_id: str) -> dict[str, str]:
    if not consultant.session_store.clear(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "reset", "session_id": session_id}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    if not consultant.session_store.delete(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}
