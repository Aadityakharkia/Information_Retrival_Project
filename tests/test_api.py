"""Web application API tests (FastAPI TestClient against a small in-memory collection)."""
import io
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from searchbridge.documents import load_directory  # noqa: E402
from searchbridge.engine import EngineConfig, SearchEngine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os
    os.environ["SEARCHBRIDGE_LIBRARY"] = str(tmp_path_factory.mktemp("lib"))
    import importlib
    srv = importlib.import_module("app.server")
    srv.LIBRARY = Path(os.environ["SEARCHBRIDGE_LIBRARY"])
    c = srv.COLLECTIONS["cs"]
    c.engine = SearchEngine.from_documents(load_directory(ROOT / "data/sample"), EngineConfig(lsa_dim=5))
    c.status = "ready"
    srv.COLLECTIONS["cranfield"].status = "building"
    return TestClient(srv.app)          # no context manager -> start-up indexing threads do not run


def test_collections_and_search(client):
    info = client.get("/api/collections").json()
    assert info["default"] in {"cs", "research"} and {m["id"] for m in info["modes"]} >= {"bridge", "bm25", "boolean"}
    r = client.get("/api/search", params={"c": "cs", "q": "pagerank random surfer", "k": 3}).json()
    assert r["hits"][0]["doc_id"] == "pagerank.md"
    assert {"lexical", "semantic", "matched", "terms"} <= set(r["hits"][0]["signal"])
    assert "facets" in r and r["mode_name"] == "Smart"
    assert client.get("/api/search", params={"c": "cs", "q": "x", "mode": "nope"}).status_code == 422
    assert client.get("/api/search", params={"c": "cranfield", "q": "x"}).status_code == 503


def test_document_related_feedback_compare(client):
    d = client.get("/api/doc", params={"c": "cs", "id": "pagerank.md", "q": "pagerank"}).json()
    assert "<mark>" in d["html"] and d["title"]
    assert client.get("/api/doc", params={"c": "cs", "id": "nope"}).status_code == 404
    rel = client.get("/api/related", params={"c": "cs", "id": "pagerank.md"}).json()
    assert rel and set(rel[0]["components"]) == {"semantic", "lexical", "entities", "graph"}
    fb = client.post("/api/feedback", json={"c": "cs", "q": "ranking", "relevant": ["bm25_ranking.md"]}).json()
    assert fb[0]["doc_id"] == "bm25_ranking.md"
    cmp = client.get("/api/compare", params={"c": "cs", "q": "ranking", "a": "bm25", "b": "dense"}).json()
    assert 0 <= cmp["jaccard"] <= 1 and cmp["a_name"] == "BM25"


def test_suggest_insights_postings_trust(client):
    assert client.get("/api/suggest", params={"c": "cs", "q": "rele"}).json()["suggestions"]
    ins = client.get("/api/insights", params={"c": "cs"}).json()
    assert ins["stats"]["documents"] == 7 and ins["zipf"]["points"]
    p = client.get("/api/postings", params={"c": "cs", "term": "ranking"}).json()
    assert p["df"] >= 1 and p["postings"]
    t = client.post("/api/trust/check", json={"text": "SHOCKING miracle!!! mail me a@b.com"}).json()
    assert t["flag"] == "low-credibility" and "[EMAIL]" in t["redacted"]
    assert client.get("/api/kg", params={"c": "cs"}).status_code == 200


def test_library_upload_rejects_bad_types(client):
    r = client.post("/api/library/upload", files=[("files", ("x.exe", io.BytesIO(b"MZ"), "application/octet-stream"))]).json()
    assert r["saved"] == [] and r["rejected"][0]["name"] == "x.exe"
    r = client.post("/api/library/upload", files=[("files", ("note.txt", io.BytesIO(b"hello library"), "text/plain"))]).json()
    assert r["saved"] == ["note.txt"]
    assert any(f["name"] == "note.txt" for f in client.get("/api/library").json()["files"])


def test_frontend_served(client):
    assert "SearchBridge" in client.get("/").text
    assert client.get("/static/papers/app.js").status_code == 200


def test_upload_rejects_invalid_replacement_without_losing_search(tmp_path, monkeypatch):
    from app import server

    library = tmp_path / "library"
    monkeypatch.setattr(server, "LIBRARY", library)
    monkeypatch.setattr(server, "CACHE", tmp_path / "cache")
    collection = server.Collection("library", "Library", "", server._library_docs, [library], encoder="lsa")
    monkeypatch.setitem(server.COLLECTIONS, "library", collection)
    client = TestClient(server.app)
    original = b'[{"id":"one","text":"saffron crocus flowers"}]'
    def upload(data):
        return client.post("/api/library/upload", files={"files": ("notes.json", data, "application/json")}).json()

    assert upload(original)["saved"] == ["notes.json"]
    # Wait for the real background worker before querying.
    import time
    deadline = time.monotonic() + 15
    while collection.status in {"idle", "building"} and time.monotonic() < deadline:
        time.sleep(0.01)
    for bad in (b'{"unfinished":', b'[{"id":"one","text":42}]'):
        result = upload(bad)
        assert not result["saved"] and result["rejected"][0]["name"] == "notes.json"
        assert (library / "notes.json").read_bytes() == original
        response = client.get("/api/search", params={"c": "library", "q": "saffron", "log": False})
        assert response.status_code == 200 and response.json()["hits"][0]["doc_id"] == "one"

    previous = collection.engine
    cache = next(server.CACHE.glob("library-*.pkl"))
    def fail_save(candidate, path):
        assert server.eng("library") is previous
        Path(path).write_bytes(b"partial")
        raise OSError("disk full")
    monkeypatch.setattr(SearchEngine, "save", fail_save)
    collection.build(force=True)
    assert server.eng("library") is previous and collection.error == "disk full"
    assert SearchEngine.load(cache).docs[0].doc_id == "one"
