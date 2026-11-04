"""Exact ASGI entrypoint and a minimal, credential-free serverless-style bundle."""

import ast
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag.config.settings import AppSettings

ROOT = Path(__file__).resolve().parents[1]


def load_entrypoint():
    return runpy.run_path(str(ROOT / "app.py"))["app"]


def test_vercel_style_discovery_selects_root_entrypoint():
    # Mirror the top-level Assign/AnnAssign/FunctionDef/ImportFrom rules in
    # vercel_python_analysis/src/entrypoint.rs; do not descend into if branches.
    def detects_app(path):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign):
                names = [node.target.id] if isinstance(node.target, ast.Name) else []
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [node.name]
            elif isinstance(node, ast.ImportFrom):
                names = [alias.asname or alias.name for alias in node.names]
            else:
                names = []
            if {"app", "application"}.intersection(names):
                return True
        return False

    candidates = [
        ROOT / directory / f"{filename}.py"
        for directory in ("", "src", "app", "api")
        for filename in ("app", "index", "server", "main", "wsgi", "asgi")
    ]
    selected = next(p for p in candidates if p.is_file() and detects_app(p))
    assert selected == ROOT / "app.py"
    tree = ast.parse(selected.read_text(encoding="utf-8"))
    assert any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "app" for t in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "create_application"
        for node in tree.body
    )


@pytest.mark.parametrize("mode", [None, "rag", " RAG "])
def test_fresh_process_production_selection_preserves_export(mode):
    clean = {
        k: os.environ[k]
        for k in ["SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"]
        if k in os.environ
    }
    clean.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    if mode is not None:
        clean["SAP_APP_MODE"] = mode
    script = r"""
import importlib.abc,sys,types
class NoDemo(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith('offline_demo'):
            raise AssertionError('Production mode imported demo')
sys.meta_path.insert(0,NoDemo())
production=types.ModuleType('api.main')
production.app=object()
sys.modules['api.main']=production
from app import app,create_application
assert app is production.app
assert callable(create_application)
print('existing production export preserved')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=clean,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "existing production export preserved"
    assert result.stderr.strip() == "SAP application mode: rag"


@pytest.mark.parametrize("mode", [None, "", "rag", " RAG "])
def test_default_rag_exports_the_existing_application(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("SAP_APP_MODE", raising=False)
    else:
        monkeypatch.setenv("SAP_APP_MODE", mode)
    original = FastAPI()
    production = ModuleType("api.main")
    production.app = original
    monkeypatch.setitem(sys.modules, "api.main", production)
    assert load_entrypoint() is original


@pytest.mark.parametrize("mode", ["demo", " DEMO ", "Demo"])
def test_demo_does_not_load_provider_settings_or_constructors(monkeypatch, mode):
    monkeypatch.setenv("SAP_APP_MODE", mode)

    def forbidden(*args, **kwargs):
        raise AssertionError("Production initialization is forbidden")

    monkeypatch.setattr(AppSettings, "from_env", forbidden)
    monkeypatch.setattr("rag.consultant.SemanticRetriever", forbidden)
    monkeypatch.setattr("rag.consultant.ResponseGenerator", forbidden)
    with TestClient(load_entrypoint()) as client:
        response = client.get("/health")
        assert response.json() == {"status": "ok"}
        assert response.headers["X-SAP-Mode"] == "TEST_ONLY-OFFLINE"


@pytest.mark.parametrize("mode", ["production", "demoo", "true"])
def test_invalid_mode_fails_before_importing_either_application(monkeypatch, mode):
    monkeypatch.setenv("SAP_APP_MODE", mode)
    import builtins

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in ("api.main", "offline_demo.application"):
            raise AssertionError("Invalid mode imported an application")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(ValueError, match="SAP_APP_MODE must be"):
        load_entrypoint()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SAP_APP_MODE", "demo")
    with TestClient(load_entrypoint()) as client:
        yield client


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "query,count",
    [
        ("What is ME21N used for in SAP?", 1),
        ("What is the difference between ME21N and ME23N?", 2),
    ],
)
def test_deployment_routes_return_cited_scoped_answers(client, query, count, streaming):
    response = client.post(
        "/chat/stream" if streaming else "/chat", json={"query": query}
    )
    assert response.status_code == 200
    if streaming:
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        result = events[-1]
        assert result["type"] == "done"
        assert not any(e["type"] == "error" for e in events)
        assert (
            next(e["sources"] for e in events if e["type"] == "sources")
            == result["sources"]
        )
    else:
        result = response.json()
    assert result["complete"] is True
    assert "create a purchase order" in result["answer"]
    assert "SAP ERP 6.0 EHP5" in result["answer"]
    assert len(result["sources"]) == count
    for source in result["sources"]:
        assert f"[{source['citation_handle']}]" in result["answer"]
        assert source["source_kind"] == "demo_reference"


@pytest.mark.parametrize(
    "query", ["What is ZDEMO999?", "What is FFC's approval limit?"]
)
def test_unknown_or_private_questions_do_not_acquire_sources(client, query):
    result = client.post("/chat", json={"query": query}).json()
    assert result["complete"] is True and result["sources"] == []
    assert (
        "won't guess" in result["answer"] or "no supporting fixture" in result["answer"]
    )


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/static/js/app.js",
        "/static/js/background.js",
        "/static/css/style.css",
        "/static/assets/sap_logo.png",
    ],
)
def test_required_assets_and_offline_route_precedence(client, path):
    response = client.get(path)
    assert response.status_code == 200
    if path == "/":
        assert "TEST_ONLY / DEMO / SIMULATED" in response.text
        assert "https://fonts" not in response.text
    if path == "/static/js/app.js":
        assert "const OFFLINE_CITATION_TITLES" in response.text
        assert "function readableReferences" in response.text
        assert "ME21N" in response.text
        assert "no-store" in response.headers["cache-control"]


def test_warm_session_isolation_corrections_and_delete(client):
    def ask(query, sid):
        return client.post("/chat", json={"query": query, "session_id": sid}).json()

    first = ask("What should I do if a goods receipt fails?", "TEST_ONLY_CASE_A")
    assert first["phase"] == "clarifying"
    assert ask("not sure", first["session_id"])["phase"] == "clarifying"
    assert ask("no error message", first["session_id"])["phase"] == "preliminary"
    ask("Actually transaction is MIGO", first["session_id"])
    engine = client.app.state.engine
    assert (
        engine.diagnosis_store.get(first["session_id"]).answers["transaction"] == "MIGO"
    )
    other = ask("My supplier invoice is not processing", "TEST_ONLY_CASE_B")
    assert other["phase"] == "clarifying"
    assert engine.diagnosis_store.get(other["session_id"]).answers == {}
    assert client.delete(f"/sessions/{first['session_id']}").status_code == 200
    assert (
        client.post(
            "/chat", json={"query": "not sure", "session_id": first["session_id"]}
        ).status_code
        == 404
    )
    assert engine.diagnosis_store.get(other["session_id"]) is not None


def test_cold_instance_does_not_restore_canonical_state_from_session_id(monkeypatch):
    monkeypatch.setenv("SAP_APP_MODE", "demo")
    first_app, second_app = load_entrypoint(), load_entrypoint()
    with TestClient(first_app) as first, TestClient(second_app) as second:
        result = first.post(
            "/chat", json={"query": "My PO is not releasing in ME29N"}
        ).json()
        sid = result["session_id"]
        assert (
            first_app.state.engine.diagnosis_store.get(sid).answers["transaction"]
            == "ME29N"
        )
        assert second_app.state.engine.diagnosis_store.get(sid) is None
        second.post("/chat", json={"query": "not sure", "session_id": sid})
        state = second_app.state.engine.diagnosis_store.get(sid)
        assert not state.answers and state.tree_id != "po_release"
        # Tombstones are instance-local too; no durable deletion is claimed.
        first.delete(f"/sessions/{sid}")
        assert second_app.state.engine.session_store.get_or_create(sid) is not None


def test_minimal_bundle_imports_and_serves_without_credentials_or_writes(tmp_path):
    # Simulate packaged runtime assets without .env, CSVs, ingestion helpers,
    # preparation records, test-result files or the repository working directory.
    for directory in ["api", "consultant", "rag", "offline_demo"]:
        for source in (ROOT / directory).rglob("*.py"):
            target = tmp_path / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    shutil.copytree(ROOT / "web", tmp_path / "web")
    for filename in [
        "app.py",
        "requirements.txt",
        "consultant/diagnosis_trees.json",
        "offline_demo/presentation.js",
        "rag/approved_sources.json",
    ]:
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / filename, target)
    clean = {
        k: os.environ[k]
        for k in ["SystemRoot", "WINDIR", "PATH", "TEMP", "TMP"]
        if k in os.environ
    }
    clean.update(SAP_APP_MODE="demo", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    script = r"""
import importlib.abc,json,os,sys
from pathlib import Path
attempts=[]
def forbidden(*args,**kwargs):
    attempts.append("provider initialization")
    raise AssertionError("Forbidden production/provider operation")
class BlockProduction(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname == "api.main" or fullname.split('.')[0] in {"ingestion","torch","sentence_transformers","langchain_community"}:
            forbidden()
sys.meta_path.insert(0,BlockProduction())
def audit(event,args):
    if event == "open":
        path,mode,flags=args
        if flags & (os.O_WRONLY|os.O_RDWR|os.O_APPEND|os.O_CREAT):
            raise AssertionError("Runtime filesystem write")
sys.addaudithook(audit)
import dotenv,groq,pinecone,urllib.request
dotenv.load_dotenv=forbidden
groq.Groq=forbidden
pinecone.Pinecone=forbidden
urllib.request.urlopen=forbidden
from fastapi.testclient import TestClient
from app import app
from offline_demo.fixtures import records
from offline_demo.tcode_references import REFERENCES
assert not Path('.env').exists() and not Path('data').exists()
assert 'api.main' not in sys.modules
assert Path(sys.modules['offline_demo.application'].__file__).is_relative_to(Path.cwd())
with TestClient(app) as client:
    for route in ['/', '/health', '/static/js/app.js', '/static/css/style.css', '/static/assets/sap_logo.png']:
        assert client.get(route).status_code == 200
    reply=client.post('/chat',json={'query':'What is ME21N used for in SAP?'}).json()
    assert reply['sources'][0]['id']=='DEMO-REFERENCE-ME21N'
    response=client.post('/chat/stream',json={'query':"What's the difference between ME21N and ME23N?"})
    events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert events[-1]['type']=='done' and len(events[-1]['sources'])==2
    issue=client.post('/chat',json={'query':'What should I do if a goods receipt fails?'}).json()
    assert issue['phase']=='clarifying'
assert attempts==[]
print(json.dumps({'fixtures':len(records()),'scoped_references':len(REFERENCES),'provider_attempts':len(attempts),'runtime_writes':0}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=clean,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    assert "SAP application mode: demo" in result.stderr.splitlines()
    assert json.loads(result.stdout) == {
        "fixtures": 6,
        "scoped_references": 9,
        "provider_attempts": 0,
        "runtime_writes": 0,
    }
