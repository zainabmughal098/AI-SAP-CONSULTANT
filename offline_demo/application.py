"""Same FastAPI routes and consultant rules, isolated TEST_ONLY components.

Fixture responses are selected through a separate deterministic TEST_ONLY
contract. They never admit fixtures as approved SAP documentation.
"""

from offline_demo.network import install

install()  # Must precede imports that could initialize provider code.

import json  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, Response  # noqa: E402

from api.routes import WEB_DIR, install_routes  # noqa: E402
from offline_demo.fixtures import LABEL, FixtureRetriever, ForbiddenGenerator  # noqa: E402
from offline_demo.responses import (  # noqa: E402
    CATALOG,
    SOURCE_TITLES,
    DemoClassifier,
    DemoDiagnosisManager,
    select_response,
)
from offline_demo.tcode_references import REFERENCES  # noqa: E402
from rag.consultant import SAPConsultant  # noqa: E402
from rag.evidence import citation_handle  # noqa: E402
from rag.memory.conversation import ConversationStore  # noqa: E402


class OfflineConversationStore(ConversationStore):
    """Keep a deleted stream/session from recreating its state while winding down."""

    def __init__(self):
        super().__init__()
        self.deleted = set()
        self.faults = {}

    def get_or_create(self, session_id=None, max_turns=10):
        if session_id in self.deleted:
            raise HTTPException(status_code=404, detail="Conversation was deleted")
        return super().get_or_create(session_id, max_turns)

    def delete(self, session_id):
        self.deleted.add(session_id)
        self.faults.pop(session_id, None)
        if session_id in self._sessions:
            self._sessions[session_id].clear()
        return super().delete(session_id)


class OfflineConsultant(SAPConsultant):
    def __post_init__(self):
        self.settings = SimpleNamespace(max_history_turns=10, llm_model=LABEL)
        self.retriever = FixtureRetriever()
        self.generator = ForbiddenGenerator()
        self.memory = self.memory or self.session_store.get_or_create(max_turns=10)
        self.diagnosis_manager = self.diagnosis_manager or DemoDiagnosisManager(
            intent_classifier=DemoClassifier(use_llm=False),
            session_store=self.diagnosis_store,
        )
        self.diagnosis_store = self.diagnosis_manager.session_store

    def worksheet(self, query, payload, filters=None):
        return select_response(self, query, payload, filters)

    def ask(self, query, filters=None, top_k=None):
        return self.worksheet(query, super().ask(query, filters, top_k), filters)

    def ask_stream(self, query, filters=None, top_k=None):
        if (
            query == "TEST_ONLY retrieval outage"
            and self.memory.session_id not in self.fault_state
        ):
            self.fault_state[self.memory.session_id] = True
            self.retriever.fail_once = True
        if query == "TEST_ONLY delayed response":
            yield {"type": "session", "session_id": self.memory.session_id}
            yield {
                "type": "status",
                "message": "TEST_ONLY waiting; Stop is available...",
            }
            time.sleep(0.6)  # Bounded local fault fixture; no upstream operation.
        events = super().ask_stream(query, filters, top_k)
        try:
            while self.memory.session_id not in getattr(
                self.session_store, "deleted", ()
            ):
                try:
                    event = next(events)
                except StopIteration:
                    break
                if self.memory.session_id in getattr(self.session_store, "deleted", ()):
                    break
                if event.get("type") in ("token", "sources"):
                    continue  # Never flash the production refusal before selecting demo output.
                if event.get("type") == "done":
                    event = self.worksheet(query, event, filters)
                    yield {"type": "sources", "sources": event.get("sources", [])}
                    yield {"type": "token", "content": event["answer"]}
                yield event
        finally:
            events.close()
            if self.memory.session_id in getattr(self.session_store, "deleted", ()):
                self.diagnosis_manager.delete_session(self.memory.session_id)
                self.fault_state.pop(self.memory.session_id, None)


def create_app():
    engine = OfflineConsultant(session_store=OfflineConversationStore())
    faults = engine.session_store.faults
    engine.fault_state = faults
    app = FastAPI(title=f"AI SAP Consultant — {LABEL}", docs_url=None, redoc_url=None)

    def resolve(session_id):
        memory = engine.session_store.get_or_create(session_id, max_turns=10)
        active = OfflineConsultant(
            session_store=engine.session_store,
            diagnosis_manager=engine.diagnosis_manager,
            memory=memory,
        )
        active.fault_state = faults
        return active

    @app.get("/static/js/app.js", include_in_schema=False)
    def offline_controller():
        # Serve the existing controller with a small, offline-only presentation
        # adapter. No production JS, layout, CSS or source identities change.
        source = (WEB_DIR / "js/app.js").read_text(encoding="utf-8")
        start = source.index("function createSourcesPanel(")
        end = source.index("\nfunction createActionBar(", start)
        adapter = (
            Path(__file__).with_name("presentation.js").read_text(encoding="utf-8")
        )
        titles = {
            "SRC-" + digest[:20]: SOURCE_TITLES[record_id.removeprefix("TEST_ONLY-")]
            for record_id, (digest, _) in CATALOG.items()
        }
        titles.update(
            {
                citation_handle(record): f"{code} — SAP reference"
                for code, record in REFERENCES.items()
            }
        )
        source = source[:start] + adapter + source[end:]
        source = source.replace(
            "function formatMarkdown(text) {",
            "function formatMarkdown(text) {\n  text = readableReferences(text);",
        )
        return Response(
            "const OFFLINE_CITATION_TITLES = " + json.dumps(titles) + ";\n" + source,
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    # Keep the shared routes; only the offline landing text/resources differ.
    def index():
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        html = re.sub(r"\s*<link[^>]+https://[^>]+>", "", html)
        html = html.replace(
            "<title>SAP Consultant</title>", f"<title>{LABEL} — SAP Consultant</title>"
        )
        html = html.replace("Grounded RAG</div>", f"{LABEL}</div>")
        html = html.replace(
            "SAP Consultant uses your knowledge base. Verify critical SAP steps before production use.",
            "Offline TEST_ONLY simulation. No SAP access, approved knowledge or provider calls.",
        )
        return HTMLResponse(html)

    @app.middleware("http")
    async def offline_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; font-src 'self'; "
            "img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'"
        )
        response.headers["X-SAP-Mode"] = "TEST_ONLY-OFFLINE"
        return response

    install_routes(app, resolve, engine, index_response=index)
    app.state.engine = engine
    return app
