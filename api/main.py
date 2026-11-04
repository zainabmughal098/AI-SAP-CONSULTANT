"""Production bootstrap. Offline testing uses offline_demo.application instead."""

from fastapi import FastAPI

from api.routes import ChatRequest, ChatResponse, install_routes
from rag.config.settings import AppSettings
from rag.consultant import SAPConsultant

__all__ = ["ChatRequest", "ChatResponse", "app", "get_active_consultant"]

app = FastAPI(title="AI SAP Consultant", version="1.0.0")
settings = AppSettings.from_env()
consultant = SAPConsultant(settings=settings)


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


install_routes(app, lambda session_id: get_active_consultant(session_id), consultant)
