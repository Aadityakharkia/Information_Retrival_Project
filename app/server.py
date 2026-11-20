"""SearchBridge web application (FastAPI backend + single-page frontends).

    uvicorn app.server:app --port 8000        then open http://127.0.0.1:8000

  /          SearchBridge search interface (API under /api)

Collections are indexed in background threads on start-up and cached in .cache/ so later
starts are instant. Uploaded files go to data/library/ and form the "My Library" collection.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import threading
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from searchbridge.documents import Document, load_cranfield, load_directory, load_file, load_jsonl  # noqa: E402
from searchbridge.engine import MODE_INFO, MODES, EngineConfig, SearchEngine  # noqa: E402
from searchbridge.retrieval.bridge_prf import BridgePRFConfig  # noqa: E402
from searchbridge.index.compression import compression_report  # noqa: E402
from searchbridge.index.laws import heaps_fit, zipf_fit  # noqa: E402
from searchbridge.responsible.credibility import credibility  # noqa: E402
from searchbridge.responsible.privacy import find_pii, redact  # noqa: E402
from searchbridge.personal import InteractionStore, PersonalContext, build_profile  # noqa: E402

log = logging.getLogger("searchbridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

CACHE = Path(os.environ.get("SEARCHBRIDGE_CACHE", Path.home() / ".cache" / "searchbridge"))   # outside iCloud/Dropbox folders
LIBRARY = Path(os.environ.get("SEARCHBRIDGE_LIBRARY", ROOT / "data/library"))
ALLOWED = {".pdf", ".txt", ".md", ".html", ".htm", ".json", ".jsonl"}
CODE_VERSION = "5"   # bump to invalidate cached indexes after engine changes


class Collection:
    def __init__(self, cid: str, name: str, description: str, loader: Callable[[], List[Document]],
                 sources: List[Path], ontology: bool = True, encoder: str = "auto"):
        self.id, self.name, self.description = cid, name, description
        self.encoder = encoder
        self.loader, self.sources, self.ontology = loader, sources, ontology
        self.engine: Optional[SearchEngine] = None
        self.status, self.error, self.progress_started = "idle", "", 0.0
        self.lock = threading.Lock()

    def fingerprint(self) -> str:
        h = hashlib.sha1(f"{CODE_VERSION}:{self.encoder}:{_has_sbert()}".encode())
        for src in self.sources:
            files = [src] if src.is_file() else sorted(p for p in src.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(src).parts)) if src.exists() else []
            for f in files:
                st = f.stat()
                h.update(f"{f}:{st.st_size}:{st.st_mtime_ns}".encode())
        return h.hexdigest()[:12]

    def build(self, force: bool = False) -> None:
        with self.lock:
            if self.engine is None:
                self.status = "building"
            self.error, self.progress_started = "", time.time()
            try:
                CACHE.mkdir(parents=True, exist_ok=True)
                cache = CACHE / f"{self.id}-{self.fingerprint()}.pkl"
                if cache.exists() and not force:
                    candidate = SearchEngine.load(cache)
                else:
                    docs = self.loader()
                    if not docs:
                        self.engine, self.status = None, "empty"
                        return
                    model = ROOT / "models/adaptive_cranfield.json"
                    cfg = EngineConfig(ontology_path=str(ROOT / "data/ontology.json") if self.ontology else None,
                                       adaptive_model_path=str(model) if model.exists() else None,
                                       lsa_dim=200 if len(docs) > 300 else max(2, min(50, len(docs) - 1)),
                                       encoder=self.encoder, hybrid_alpha=0.5,
                                       # app defaults chosen to be robust across both benchmarks (see REPORT §6)
                                       bridge=BridgePRFConfig(fb_docs=3, alpha=0.5))
                    candidate = SearchEngine.from_documents(docs, cfg)
                    with tempfile.NamedTemporaryFile(dir=CACHE, delete=False) as tmp:
                        pending = Path(tmp.name)
                    try:
                        candidate.save(pending)
                        pending.replace(cache)
                    finally:
                        pending.unlink(missing_ok=True)
                    for old in CACHE.glob(f"{self.id}-*.pkl"):
                        if old != cache:
                            old.unlink(missing_ok=True)
                self.engine, self.status = candidate, "ready"
                log.info("collection %s ready (%d docs)", self.id, len(self.engine.docs))
            except Exception as e:  # pragma: no cover - surfaced to UI
                log.exception("building %s failed", self.id)
                self.status = "ready" if self.engine is not None else "error"
                self.error = str(e)

    def info(self) -> Dict:
        d = {"id": self.id, "name": self.name, "description": self.description, "status": self.status, "error": self.error}
        if self.engine and self.status == "ready":
            d["stats"] = self.engine.stats()
            d["examples"] = EXAMPLES.get(self.id, [])
        return d


def _has_sbert() -> bool:
    import importlib.util
    return importlib.util.find_spec("sentence_transformers") is not None


def _library_docs() -> List[Document]:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    return load_directory(LIBRARY)


EXAMPLES = {
    "research": ["transformer language models", "graph neural networks for recommendation", "federated learning privacy",
                 "object detection in real time", "retrieval augmented generation", "edge computing for IoT",
                 "contrastive self-supervised learning", "blockchain smart contracts security", "explainable AI in healthcare",
                 "reinforcment learning robots"],
    "cs": ["query expansion for web search", "mechanism design for auctions", "peer to peer file sharing",
           "neural networks for classification", "quantum computing algorithms", '"information retrieval" AND NOT web',
           "distribted hash tables", "image compresion standards"],
    "cranfield": ["heat transfer in hypersonic boundry layers", "wing flutter at supersonic speed",
                  '"boundary layer" AND (suction OR injection)', "buckling of cylindrical shells", "shock wave author:lees"],
    "library": [],
    "web": [],
}

RESEARCH = ROOT / "data/research_papers/papers.jsonl.gz"
WEB = ROOT / "data/web/pages.jsonl.gz"


def _research_docs() -> List[Document]:
    docs = load_jsonl(RESEARCH) if RESEARCH.exists() else []
    for d in docs:   # surface OpenAlex metadata under the keys the UI shows
        d.meta["author"] = d.meta.pop("authors", "")
    return docs


COLLECTIONS: Dict[str, Collection] = {
    "research": Collection("research", "Research Papers 2016–2025",
                           "The most-cited computer-science papers of 2016–2025 across 12 subfields (from OpenAlex), with abstracts, authors, venues, keywords and citations",
                           _research_docs, [ROOT / "data/research_papers"]),
    "cs": Collection("cs", "Classic CS Papers 1998–2007",
                     "2,243 older computer-science papers: 243 full ACM conference papers (SemEval-2010) and 2,000 journal abstracts (Inspec), with author keyphrases and citations",
                     lambda: load_jsonl(ROOT / "data/cs_papers/papers.jsonl.gz"), [ROOT / "data/cs_papers"]),
    "cranfield": Collection("cranfield", "Cranfield (benchmark)",
                            "The classic Cranfield 1400 aerodynamics test collection with 225 judged queries, used for evaluation",
                            lambda: load_cranfield(ROOT / "data/cranfield")[0], [ROOT / "data/cranfield"], encoder="lsa"),
    "web": Collection("web", "Web pages", "Pages collected by the built-in crawler (robots.txt-compliant), with their real hyperlinks",
                      lambda: load_jsonl(WEB) if WEB.exists() else [], [ROOT / "data/web"], ontology=False),
    "library": Collection("library", "My Library", "Your own PDFs, text, Markdown and HTML files — upload them on the Library page",
                          _library_docs, [LIBRARY], ontology=False),
}
DEFAULT = "research" if RESEARCH.exists() else "cs"

app = FastAPI(title="SearchBridge", version="3.0.0",
              description="Intelligent document search: hybrid lexical + semantic retrieval with explainable ranking.")


@app.on_event("startup")
def _startup() -> None:
    def run():
        order = [DEFAULT] + [c for c in ("research", "cs", "web", "library", "cranfield") if c != DEFAULT]
        for cid in order:
            if (cid == "research" and not RESEARCH.exists()) or (cid == "web" and not WEB.exists()):
                COLLECTIONS[cid].status = "missing"
                continue
            COLLECTIONS[cid].build()
    threading.Thread(target=run, daemon=True).start()


def eng(cid: str) -> SearchEngine:
    c = COLLECTIONS.get(cid)
    if not c:
        raise HTTPException(404, f"unknown collection {cid}")
    if c.status == "missing":
        raise HTTPException(409, "No pages crawled yet. Crawl a site from the Library page." if cid == "web"
                            else "This collection has not been downloaded yet. Run: python scripts/fetch_openalex.py")
    if c.status == "empty":
        raise HTTPException(409, "This collection is empty — upload documents on the Library page first.")
    if c.status != "ready" or c.engine is None:
        raise HTTPException(503, f"{c.name} is still being indexed ({c.status}{': ' + c.error if c.error else ''})")
    return c.engine


def _clean(o):
    """JSON-safe conversion (numpy scalars, tuples)."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


# ------------------------------------------------------------------ API
@app.get("/api/collections")
def collections():
    return {"default": DEFAULT, "collections": [c.info() for c in COLLECTIONS.values()],
            "modes": [{"id": m, "name": MODE_INFO[m][0], "description": MODE_INFO[m][1]} for m in MODES]}


# ------------------------------------------------------------------ users & search memory
STORE = InteractionStore()
K_ANON = 3                       # a query is suggested to others only after this many different people ran it
_profiles: Dict[tuple, object] = {}


@app.middleware("http")
async def _user_cookie(request: Request, call_next):
    """Anonymous per-browser profile id. Interaction history is keyed by it and never mixed between users."""
    uid = request.cookies.get("sb_uid", "")
    new = not (len(uid) == 32 and uid.isalnum())
    if new:
        import uuid
        uid = uuid.uuid4().hex
    request.state.uid = uid
    response = await call_next(request)
    if new:
        response.set_cookie("sb_uid", uid, max_age=2 * 365 * 86400, httponly=True, samesite="lax")
    return response


def _profile(uid: str, cid: str):
    v = STORE.version(uid, cid)
    key = (uid, cid)
    hit = _profiles.get(key)
    if hit is None or hit.version != str(v):
        hit = build_profile(uid, cid, STORE.events(uid, cid), str(v))
        _profiles[key] = hit
    return hit


def personal_context(e: SearchEngine, uid: str, cid: str) -> Optional[PersonalContext]:
    prof = _profile(uid, cid)
    if prof.empty:
        return None
    return PersonalContext(prof, e.index.doc_index, e.dense.emb, e.analyzer, e.out_links, e.in_links)


@app.get("/api/search")
def search(request: Request, c: str = DEFAULT, q: str = "", mode: str = "smart", k: int = Query(10, ge=1, le=50),
           offset: int = Query(0, ge=0), spell: bool = True, diversify: bool = False, mmr: float = 0.7, pagerank: float = 0.0,
           fair: str = "", category: str = "", type: str = "", topic: str = "", tag: str = "", venue: str = "",
           clusters: bool = True, personalize: bool = True, context: str = "", log: bool = True):
    if mode not in MODES:
        raise HTTPException(422, f"mode must be one of {MODES}")
    e = eng(c)
    uid = request.state.uid
    filters = {"category": category, "type": type, "topic": topic, "tag": tag, "venue": venue}
    pctx = personal_context(e, uid, c) if personalize and mode == "smart" else None
    resp = e.search(q, mode=mode, k=k, offset=offset, spell=spell, diversify=diversify, mmr_lambda=mmr,
                    pagerank_weight=pagerank, fair_group=fair or None, filters={f: v for f, v in filters.items() if v},
                    personal=pctx, context=context, user=uid)
    if log and q.strip() and offset == 0:
        STORE.log(uid, c, "search", query=q.strip())
        STORE.log_impressions(uid, c, q.strip(), [h.doc_id for h in resp.hits[:10]])
    out = asdict(resp)
    if clusters and offset == 0 and len(resp.hits) >= 6:
        out["clusters"] = [{"label": v["label"], "docs": v["docs"]} for v in e.cluster_results(resp, 4).values()]
    out["mode_name"] = MODE_INFO[resp.mode][0]
    out["memory"] = {"active": pctx is not None, "paused": STORE.paused(uid)}
    return _clean(out)


@app.get("/api/suggest")
def suggest(request: Request, c: str = DEFAULT, q: str = ""):
    try:
        e = eng(c)
    except HTTPException:
        return {"suggestions": [], "completions": [], "history": [], "popular": [], "titles": [], "related": []}
    prof = _profile(request.state.uid, c)
    popular = {qq: len(users) for qq, users in STORE.query_users(c).items() if len(users) >= K_ANON}
    out = e.suggest(q, prof.recent_queries, popular)
    out["suggestions"] = out["history"] + out["completions"]          # flat list for simple clients
    return out


class Event(BaseModel):
    c: str = DEFAULT
    kind: str
    doc: str = ""
    to_doc: str = ""
    q: str = ""
    rank: int = 0
    value: float = 0.0
    source: str = ""


@app.post("/api/events")
def log_event(ev: Event, request: Request):
    if ev.kind not in {"open", "dwell", "link", "feedback"}:
        raise HTTPException(422, "kind must be open, dwell, link or feedback")
    e = eng(ev.c)
    for d in (ev.doc, ev.to_doc):
        if d and d not in e.index.doc_index:
            raise HTTPException(404, f"unknown document {d}")
    value = max(0.0, min(ev.value, 3600.0)) if ev.kind == "dwell" else (1.0 if ev.value > 0 else -1.0 if ev.value < 0 else 0.0) if ev.kind == "feedback" else 0.0
    ok = STORE.log(request.state.uid, ev.c, ev.kind, query=ev.q, doc=ev.doc, to_doc=ev.to_doc, rank=ev.rank, value=value, source=ev.source)
    return {"recorded": ok}


@app.get("/api/me")
def me(request: Request, c: str = DEFAULT):
    """Everything the engine has learned about this browser, so it can be inspected and reset."""
    e = eng(c)
    uid = request.state.uid
    prof = _profile(uid, c)
    def title(d):
        return e.docs[e.index.doc_index[d]].display_title if d in e.index.doc_index else d
    docs = sorted(prof.evidence.items(), key=lambda x: -prof.affinity.get(x[0], 0))
    useful = [{"id": d, "title": title(d), "affinity": round(prof.affinity.get(d, 0), 3), "opens": x.opens,
               "dwell": round(x.dwell), "links_out": x.links_out, "feedback": x.feedback, "reasons": x.reasons(),
               "last": x.last} for d, x in docs if prof.affinity.get(d, 0) > 0.05][:15]
    disliked = [{"id": d, "title": title(d), "affinity": round(prof.affinity[d], 3), "reasons": x.reasons()}
                for d, x in docs if prof.affinity.get(d, 0) < -0.05][:10]
    topics: Counter = Counter()
    for d, a in prof.positive().items():
        if d in e.index.doc_index:
            topics[e.doc_topic[e.index.doc_index[d]]] += a
    links = [ev for ev in STORE.events(uid, c, ["link"])][-10:]
    return _clean({"user": uid[:6] + "…", "paused": STORE.paused(uid), "events": prof.n_events,
                   "useful": useful, "not_useful": disliked,
                   "interests": [{"topic": t, "weight": round(w, 2)} for t, w in topics.most_common(6)],
                   "recent_queries": [q for q, _ in prof.recent_queries[:12]],
                   "links": [{"from": title(x["doc"]), "from_id": x["doc"], "to": title(x["to_doc"]), "to_id": x["to_doc"]} for x in reversed(links)],
                   "half_life_days": 21})


@app.delete("/api/me/history")
def clear_history(request: Request, c: str = ""):
    n = STORE.clear(request.state.uid, c or None)
    _profiles.clear()
    return {"deleted": n}


class Pause(BaseModel):
    paused: bool


@app.post("/api/me/pause")
def pause(p: Pause, request: Request):
    STORE.set_paused(request.state.uid, p.paused)
    return {"paused": p.paused}


@app.get("/api/doc")
def document(c: str, id: str, q: str = ""):
    e = eng(c)
    if id not in e.index.doc_index:
        raise HTTPException(404, "unknown document")
    d = e.document(id, q)
    titles = lambda ids: [{"id": i, "title": e.docs[e.index.doc_index[i]].display_title} for i in ids]
    d["cites"], d["cited_by"] = titles(d["cites"]), titles(d["cited_by"])
    src = d["meta"].get("source", "")
    d["file_url"] = f"/api/library/file/{Path(src).name}" if c == "library" and src else None
    return _clean(d)


@app.get("/api/related")
def related(c: str, id: str, k: int = 5):
    e = eng(c)
    if id not in e.index.doc_index:
        raise HTTPException(404, "unknown document")
    return [{"id": d, "title": t, "score": s, "components": p} for d, t, s, p in e.related_documents(id, k)]


class Feedback(BaseModel):
    c: str = DEFAULT
    q: str
    relevant: List[str]
    nonrelevant: List[str] = []
    k: int = 10


@app.post("/api/feedback")
def feedback(fb: Feedback):
    return _clean([asdict(h) for h in eng(fb.c).feedback_hits(fb.q, fb.relevant, fb.nonrelevant, fb.k)])


@app.get("/api/compare")
def compare(c: str = DEFAULT, q: str = "", a: str = "bm25", b: str = "bridge", k: int = 10):
    if a not in MODES or b not in MODES:
        raise HTTPException(422, "unknown mode")
    res = eng(c).compare(q, [a, b], k)
    return _clean({"a": asdict(res["runs"][a]), "b": asdict(res["runs"][b]), "jaccard": res["jaccard"], "rbo": res["rbo"],
                   "a_name": MODE_INFO[a][0], "b_name": MODE_INFO[b][0]})


@app.get("/api/kg")
def kg(c: str = DEFAULT, q: str = "", n: int = Query(40, ge=5, le=120), seeds: str = "", strict: bool = False):
    return _clean(eng(c).kg_view(q, n, [x for x in seeds.split("|") if x], strict))


_insight_cache: Dict[str, Dict] = {}


@app.get("/api/insights")
def insights(c: str = DEFAULT):
    e = eng(c)
    key = f"{c}-{id(e)}"
    if key not in _insight_cache:
        cf = e.index.collection_tf()
        zf, ranks, freqs = zipf_fit(cf)
        idx = np.unique(np.logspace(0, math.log10(len(ranks)), 60).astype(int) - 1)
        stream = (t for d in e.docs[:1500] for t in e.analyzer(d.full_text[:6000]))
        hf, T, M = heaps_fit(stream, 40)
        rep = compression_report(e.index.postings)
        top = [(e.surface.get(t, t), n) for t, n in cf.most_common(25)]
        _insight_cache[key] = {
            "stats": e.stats(),
            "zipf": {"exponent": zf.exponent, "r2": zf.r2, "points": [[float(ranks[i]), float(freqs[i])] for i in idx]},
            "heaps": {"k": hf.k, "b": hf.b, "r2": hf.r2, "points": [[float(t), float(m)] for t, m in zip(T, M)]},
            "compression": [{"structure": n, "bytes": b, "ratio": r} for n, b, r in rep.as_rows()],
            "top_terms": top, "topics": Counter(e.doc_topic).most_common(),
            "pagerank_top": [{"id": e.docs[i].doc_id, "title": e.docs[i].display_title, "score": float(e.pagerank[i])}
                             for i in np.argsort(-e.pagerank)[:8]],
        }
    return _clean(_insight_cache[key])


@app.get("/api/postings")
def postings(c: str = DEFAULT, term: str = ""):
    e = eng(c)
    t = e.analyzer.analyze_term(term)
    p = e.index.get_postings(t) if t else {}
    from searchbridge.index.compression import gamma_encode, to_gaps, vb_encode
    ids = sorted(p)
    gaps = to_gaps(ids)
    return {"term": term, "stem": t, "df": len(p), "idf": round(e.index.idf(t), 3) if t else 0,
            "postings": [{"doc": e.docs[d].doc_id, "title": e.docs[d].display_title[:80], "tf": len(pos), "positions": pos[:12]}
                         for d, pos in sorted(p.items(), key=lambda x: -len(x[1]))[:15]],
            "gaps_preview": gaps[:15], "vb_bytes": len(vb_encode(gaps)), "gamma_bits": len(gamma_encode(gaps)), "raw_bytes": 4 * len(ids),
            "wildcard": e.kgram.wildcard(term.lower() if "*" in term else term.lower()[:4] + "*", 20),
            "spelling": e.kgram.suggest(term.lower()) if term and term.isalpha() else []}


# ------------------------------------------------------------------ Insights (advanced views)
@app.get("/api/lab/links")
def lab_links(c: str = DEFAULT):
    return _clean(eng(c).link_report())


@app.get("/api/lab/hits")
def lab_hits(c: str = DEFAULT, q: str = ""):
    return _clean(eng(c).hits_report(q)) if q.strip() else {"query": "", "authorities": [], "hubs": []}


@app.get("/api/lab/topics")
def lab_topics(c: str = DEFAULT):
    return _clean(eng(c).topic_report())


@app.get("/api/lab/duplicates")
def lab_duplicates(c: str = DEFAULT):
    return _clean(eng(c).duplicate_report())


CRAWL: Dict = {"status": "idle"}


class CrawlIn(BaseModel):
    seed: str
    max_pages: int = 200
    depth: int = 2
    prefix: str = ""
    exclude: List[str] = []


@app.post("/api/crawl")
def start_crawl(ci: CrawlIn):
    if CRAWL.get("status") == "running":
        raise HTTPException(409, "A crawl is already running")
    if not ci.seed.startswith(("http://", "https://")):
        raise HTTPException(422, "Seed must be an http(s) URL")
    from scripts.crawl_web import crawl

    def run():
        CRAWL.update(status="running", seed=ci.seed, started=time.time(), error="", progress={}, max_pages=ci.max_pages)
        try:
            CRAWL["stats"] = crawl([ci.seed], max(1, min(ci.max_pages, 1000)), max(0, min(ci.depth, 4)), 1.0,
                                   ci.prefix or None, ci.exclude, log=log.info,
                                   progress=lambda st: CRAWL.update(progress=st))
            if CRAWL["stats"]["pages"] == 0:
                reasons = CRAWL["stats"].get("error_examples") or CRAWL["stats"].get("blocked_examples") or []
                CRAWL.update(status="error", error="No pages were fetched. " + (reasons[0] if reasons else
                             "The start page was refused by robots.txt or is outside the path you gave."))
            else:
                CRAWL["status"] = "done"
                COLLECTIONS["web"].build(force=True)
        except Exception as ex:  # pragma: no cover - network dependent
            CRAWL.update(status="error", error=str(ex))
    threading.Thread(target=run, daemon=True).start()
    return {"status": "started"}


@app.get("/api/crawl")
def crawl_status():
    stats = ROOT / "data/web/crawl_stats.json"
    return {**CRAWL, "last": json.loads(stats.read_text()) if stats.exists() else None}


@app.get("/api/eval")
def evaluation():
    f = ROOT / "results/results.json"
    if not f.exists():
        raise HTTPException(404, "Run `python experiments/run_benchmark.py` first.")
    data = json.loads(f.read_text())
    figs = sorted(p.name for p in (ROOT / "results/figures").glob("*.png"))
    extra = ROOT / "results/keyphrase/results.json"
    pers = ROOT / "results/personalization/results.json"
    return {"cranfield": data, "figures": figs, "keyphrase": json.loads(extra.read_text()) if extra.exists() else None,
            "personalization": json.loads(pers.read_text()) if pers.exists() else None}


app.mount("/figures", StaticFiles(directory=str(ROOT / "results/figures"), check_dir=False), name="figures")


# ------------------------------------------------------------------ library management
@app.get("/api/library")
def library_list():
    LIBRARY.mkdir(parents=True, exist_ok=True)
    files = [{"name": p.name, "bytes": p.stat().st_size, "modified": p.stat().st_mtime, "type": p.suffix.lower().lstrip(".").upper()}
             for p in sorted(LIBRARY.iterdir()) if p.is_file() and p.suffix.lower() in ALLOWED]
    return {"files": files, "status": COLLECTIONS["library"].status, "error": COLLECTIONS["library"].error}


@app.post("/api/library/upload")
async def library_upload(files: List[UploadFile] = File(...)):  # noqa: B008
    LIBRARY.mkdir(parents=True, exist_ok=True)
    saved, rejected = [], []
    for f in files:
        name = Path(f.filename or "").name
        if Path(name).suffix.lower() not in ALLOWED:
            rejected.append({"name": name, "reason": "unsupported type"})
            continue
        data = await f.read()
        if len(data) > 50_000_000:
            rejected.append({"name": name, "reason": "larger than 50 MB"})
            continue
        if name.startswith("."):
            rejected.append({"name": name, "reason": "hidden files are excluded from the index"})
            continue
        with tempfile.TemporaryDirectory(dir=LIBRARY, prefix=".upload-") as staging:
            candidate = Path(staging) / name
            candidate.write_bytes(data)
            try:
                if candidate.suffix.lower() in {".json", ".jsonl"}:
                    docs = load_jsonl(candidate)
                    if not docs or any(not doc.full_text.strip() for doc in docs):
                        raise ValueError("each record needs a title or text")
                else:
                    doc = load_file(candidate)
                    if doc is None or not doc.text.strip():
                        raise ValueError("file contains no extractable text")
            except Exception as exc:
                rejected.append({"name": name, "reason": str(exc)})
                continue
            candidate.replace(LIBRARY / name)
            saved.append(name)
    if saved:
        threading.Thread(target=COLLECTIONS["library"].build, kwargs={"force": True}, daemon=True).start()
    return {"saved": saved, "rejected": rejected}


@app.delete("/api/library/{name}")
def library_delete(name: str):
    p = LIBRARY / Path(name).name
    if not p.exists():
        raise HTTPException(404, "no such file")
    trash = LIBRARY / ".trash"
    trash.mkdir(exist_ok=True)
    shutil.move(str(p), trash / p.name)
    threading.Thread(target=COLLECTIONS["library"].build, kwargs={"force": True}, daemon=True).start()
    return {"deleted": name}


@app.get("/api/library/file/{name}")
def library_file(name: str):
    p = LIBRARY / Path(name).name
    if not p.exists():
        raise HTTPException(404, "no such file")
    return FileResponse(p)


@app.post("/api/library/load-samples")
def library_samples():
    LIBRARY.mkdir(parents=True, exist_ok=True)
    for p in (ROOT / "data/sample").iterdir():
        shutil.copy(p, LIBRARY / p.name)
    threading.Thread(target=COLLECTIONS["library"].build, kwargs={"force": True}, daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------ trust & privacy
class TextIn(BaseModel):
    text: str
    source: str = ""


@app.post("/api/trust/check")
def trust_check(t: TextIn):
    cs = credibility(t.text, t.source)
    return {"score": round(cs.score, 2), "flag": cs.flag, "reasons": cs.reasons,
            "pii": [{"type": k, "value": v} for k, v in find_pii(t.text)], "redacted": redact(t.text)}


@app.get("/api/trust/log")
def trust_log(c: str = DEFAULT):
    ql = eng(c).query_log
    return {"k": ql.k_anonymity, "logged": len(ql._records), "releasable": ql.releasable_queries(),
            "dp_counts": {q: round(v, 1) for q, v in ql.dp_counts(1.0, seed=0).items()},
            "sample": [{"user": u, "query": q} for u, q in ql._records[-8:]]}


@app.get("/api/health")
def health():
    return {"status": "ok", "collections": {c.id: c.status for c in COLLECTIONS.values()}}


# ------------------------------------------------------------------ frontend
STATIC = ROOT / "app/static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/classic")
def classic():
    """The previous interface, kept for reference."""
    return FileResponse(STATIC / "papers/index.html")


@app.exception_handler(ValueError)
def value_error(_, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})
