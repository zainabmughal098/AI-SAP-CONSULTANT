"""FastAPI server for the SAP consultant."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rag.errors import service_error

ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"


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
    error_code: str | None = None
    retryable: bool = False
    complete: bool = True
    intent: str | None = None
    phase: str | None = None


def install_routes(app, resolve_consultant, base_consultant, index_response=None):
    @app.exception_handler(Exception)
    async def unexpected_error_handler(request, exc: Exception) -> JSONResponse:
        error = service_error(exc, "generation")
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": error.message,
                "error_code": error.code,
                "retryable": error.retryable,
                "complete": False,
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index() -> FileResponse:
        if index_response is not None:
            return index_response()
        return FileResponse(WEB_DIR / "index.html")

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse | JSONResponse:
        active = resolve_consultant(request.session_id)
        payload = active.ask(
            query=request.query,
            filters=request.filters,
            top_k=request.top_k,
        )

        response = ChatResponse(
            **{k: v for k, v in payload.items() if k in ChatResponse.model_fields}
        )
        if payload.get("error"):
            return JSONResponse(
                status_code=payload.get("http_status", 503),
                content=response.model_dump(),
            )
        return response

    @app.post("/chat/stream")
    def chat_stream(request: ChatRequest) -> StreamingResponse:
        active = resolve_consultant(request.session_id)

        def event_stream():
            try:
                with closing(
                    active.ask_stream(
                        query=request.query,
                        filters=request.filters,
                        top_k=request.top_k,
                    )
                ) as events:
                    for event in events:
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:
                error = service_error(exc, "generation")
                event = {
                    "type": "error",
                    "message": error.message,
                    "error_code": error.code,
                    "retryable": error.retryable,
                    "complete": False,
                }
                yield f"data: {json.dumps(event)}\n\n"

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
        cleared = base_consultant.session_store.clear(session_id)
        base_consultant.diagnosis_manager.clear_session(session_id)
        if not cleared:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "reset", "session_id": session_id}

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, str]:
        deleted = base_consultant.session_store.delete(session_id)
        base_consultant.diagnosis_manager.delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"status": "deleted", "session_id": session_id}

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
