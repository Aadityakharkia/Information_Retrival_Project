"""Search memory, suggestions, link analysis, crawler, duplicates and categories."""
from __future__ import annotations

import gzip
import http.server
import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from searchbridge.documents import Document, load_cranfield, load_jsonl
from searchbridge.engine import EngineConfig, SearchEngine
from searchbridge.personal import InteractionStore, PersonalContext, build_profile
from searchbridge.personal import rerank

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cran():
    docs, Q, QR = load_cranfield(ROOT / "data/cranfield")
    return SearchEngine.from_documents(docs, EngineConfig(encoder="lsa", lsa_dim=100, build_kg=False)), Q, QR


def ev(kind, doc="", value=0.0, ts=None, query="", to_doc=""):
    return {"ts": ts or time.time(), "kind": kind, "query": query, "doc": doc, "to_doc": to_doc, "rank": 1, "value": value, "source": ""}


# ------------------------------------------------------------------ profile
def test_click_alone_is_weak_and_reading_is_strong():
    a = build_profile("u", "c", [ev("open", "A")]).affinity["A"]
    b = build_profile("u", "c", [ev("open", "B"), ev("dwell", "B", 90)]).affinity["B"]
    c = build_profile("u", "c", [ev("open", "C"), ev("dwell", "C", 3)]).affinity["C"]
    assert 0 < a < 0.25 < b and c < a


def test_revisits_and_links_add_up_but_stay_bounded():
    one = build_profile("u", "c", [ev("open", "A"), ev("dwell", "A", 60)]).affinity["A"]
    many = build_profile("u", "c", [ev("open", "A"), ev("dwell", "A", 60)] * 30 + [ev("link", "A", to_doc="B")] * 10)
    assert one < many.affinity["A"] < 1.0
    assert many.affinity["B"] > 0 and "B" in many.explored


def test_time_decay_and_latest_feedback_wins():
    old = time.time() - 200 * 86400
    a_old = build_profile("u", "c", [ev("open", "A", ts=old), ev("dwell", "A", 90, ts=old)]).affinity["A"]
    a_new = build_profile("u", "c", [ev("open", "A"), ev("dwell", "A", 90)]).affinity["A"]
    assert a_old < a_new / 10
    p = build_profile("u", "c", [ev("feedback", "A", 1, ts=time.time() - 10), ev("feedback", "A", -1)])
    assert p.affinity["A"] < 0


def test_shown_but_never_opened_is_slightly_demoted():
    p = build_profile("u", "c", [ev("impression", "A") for _ in range(6)])
    assert -0.3 < p.affinity["A"] < 0


def test_gate_keeps_irrelevant_documents_down():
    assert rerank.gate(0.0) == 0 and rerank.gate(0.15) == pytest.approx(0.5) and rerank.gate(0.9) == 1
    out = rerank.apply({1: 0.05, 2: 0.9}, {1: (1.0, {}, []), 2: (0.0, {}, [])}, beta=0.5)
    assert out[1] < out[2]


# ------------------------------------------------------------------ store: persistence and separation
def test_store_persists_and_separates_users(tmp_path):
    s = InteractionStore(tmp_path / "x.db")
    s.log("alice", "c", "open", doc="A")
    s.log("bob", "c", "open", doc="B")
    s2 = InteractionStore(tmp_path / "x.db")          # a new process / session
    assert [e["doc"] for e in s2.events("alice", "c")] == ["A"]
    assert [e["doc"] for e in s2.events("bob", "c")] == ["B"]
    s2.set_paused("alice", True)
    assert not s2.log("alice", "c", "open", doc="C")
    assert s2.clear("alice") == 1 and s2.events("alice", "c") == [] and s2.events("bob", "c")
    with pytest.raises(ValueError):
        s2.log("bob", "c", "hack")


# ------------------------------------------------------------------ personalised ranking on real judgements
def test_memory_helps_a_related_search_and_is_bounded(cran):
    e, Q, QR = cran
    rel = {q: {d for d, g in v.items() if g > 0} for q, v in QR.items()}
    a, b = next((a, b) for a in rel for b in rel if a != b and len(rel[a] & rel[b]) >= 2)
    shared = sorted(rel[a] & rel[b])
    events = []
    for d in shared:
        events += [ev("open", d, query=Q[a]), ev("dwell", d, 90, query=Q[a])]
    prof = build_profile("u", "cran", events, "1")
    ctx = PersonalContext(prof, e.index.doc_index, e.dense.emb, e.analyzer, e.out_links, e.in_links)
    base = [h.doc_id for h in e.search(Q[b], mode="smart", k=50, spell=False).hits]
    pers = e.search(Q[b], mode="smart", k=50, spell=False, personal=ctx)
    ranks = lambda run: [run.index(d) if d in run else 99 for d in shared]
    assert sum(ranks([h.doc_id for h in pers.hits])) < sum(ranks(base))
    assert all(abs(h.breakdown.get("personal", 0)) <= rerank.DEFAULT_BETA + 1e-9 for h in pers.hits)
    assert any(h.personal for h in pers.hits)


def test_memory_does_not_pull_in_unrelated_documents(cran):
    e, Q, QR = cran
    far = "1"                                          # a document clicked for some unrelated reason
    prof = build_profile("u", "cran", [ev("open", far), ev("dwell", far, 120)] * 3, "1")
    ctx = PersonalContext(prof, e.index.doc_index, e.dense.emb, e.analyzer, e.out_links, e.in_links)
    q = "buckling of cylindrical shells under axial compression"
    base = [h.doc_id for h in e.search(q, mode="smart", k=10).hits]
    pers = [h.doc_id for h in e.search(q, mode="smart", k=10, personal=ctx).hits]
    if far not in base:
        assert far not in pers[:3]


# ------------------------------------------------------------------ suggestions
def test_suggestions_come_from_the_index(cran):
    e, _, _ = cran
    s = e.suggest("boundary la")
    assert any(c.startswith("boundary layer") for c in s["completions"])
    assert all(c.split()[-1] in e.kgram.freq or " " in c for c in s["completions"])
    assert e.suggest("hypersonc")["correction"]
    t = e.suggest("supersonic fl")["titles"]
    assert t and all("supersonic" in x["title"].lower() for x in t)
    h = e.suggest("wing", history=[("wing flutter at high speed", 2.0)])
    assert h["history"] == ["wing flutter at high speed"]


# ------------------------------------------------------------------ crawler + link analysis
@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    (root / "robots.txt").write_text("User-agent: *\nDisallow: /private/\n")
    pages = {"wiki/a.html": ["b", "c", "private"], "wiki/b.html": ["c"], "wiki/c.html": ["a"], "wiki/d.html": ["c"],
             "wiki/e.html": [], "private/x.html": ["a"]}
    words = {"a": "pagerank link analysis random surfer", "b": "hubs and authorities hits algorithm", "c": "web crawler politeness robots",
             "d": "inverted index postings dictionary", "e": "boolean retrieval queries", "x": "secret"}
    for p, links in pages.items():
        (root / p).parent.mkdir(exist_ok=True)
        name = Path(p).stem
        hrefs = "".join(f'<a href="/{"private/x" if t == "private" else "wiki/" + t}.html">{t}</a>' for t in links)
        extra = '<a href="/wiki/d.html">d</a><a href="/wiki/e.html">e</a>' if name == "a" else ""
        (root / p).write_text(f"<html><title>Page {name}</title><body><p>{words[name]} " * 3 + f"</p>{hrefs}{extra}</body></html>")

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_crawler_respects_robots_and_scope_and_keeps_real_links(site, tmp_path):
    from scripts.crawl_web import crawl
    out = tmp_path / "pages.jsonl.gz"
    stats = crawl([f"{site}/wiki/a.html"], max_pages=20, depth=3, delay=0.0, prefix="/wiki/", exclude=[":"], out=out, log=lambda *a: None)
    docs = load_jsonl(out)
    urls = {d.doc_id for d in docs}
    assert len(docs) == 5 and not any("private" in u for u in urls)
    assert stats["robots_blocked"] + stats["out_of_scope"] >= 1
    assert all(set(d.links) <= urls for d in docs)

    e = SearchEngine.from_documents(docs, EngineConfig(encoder="lsa", lsa_dim=4, build_kg=False))
    assert e.n_links == sum(len(d.links) for d in docs) and e.graph_kind == "hyperlinks"
    v = e.pr_versions
    assert v["v1"]["mass"][-1] < 0.99                 # dead end (page e) leaks rank without teleport
    assert v["v2"]["mass"][-1] < 1.0
    assert abs(float(v["v3"]["scores"].sum()) - 1) < 1e-5
    c = e.index.doc_index[f"{site}/wiki/c.html"]
    a = e.index.doc_index[f"{site}/wiki/a.html"]
    assert set(np.argsort(-v["v3"]["scores"])[:2].tolist()) == {a, c}     # c has most in-links; a is c's only out-link
    auth, hub, edges = e.hits_scores(list(range(len(docs))))
    assert edges > 0 and max(auth, key=auth.get) == c
    r = e.search("crawler", mode="smart", k=5)
    assert r.hits and "pagerank" in r.hits[0].breakdown


def test_crawl_with_no_pages_keeps_old_collection_and_reports_why(site, tmp_path):
    from scripts.crawl_web import crawl
    out = tmp_path / "pages.jsonl.gz"
    stats = crawl([f"{site}/private/x.html"], max_pages=5, delay=0.0, out=out, log=lambda *a: None)
    assert stats["pages"] == 0 and stats["robots_blocked"] == 1 and not out.exists()
    stats = crawl([f"{site}/wiki/missing.html"], max_pages=5, delay=0.0, out=out, log=lambda *a: None)
    assert stats["pages"] == 0 and stats["error_examples"]


def test_no_links_means_no_link_signals(cran):
    e, _, _ = cran
    assert e.n_links == 0 and e.graph_kind == "none" and not e.pagerank.any()
    assert "pagerank" not in e.search("wing flutter", mode="smart", k=3).hits[0].breakdown


# ------------------------------------------------------------------ near duplicates & categories
def test_near_duplicates_are_folded():
    text = " ".join(f"word{i} topic{i % 7}" for i in range(300))
    docs = [Document("a", "Report on topics", text), Document("b", "Report on topics (copy)", text + " addendum"),
            Document("c", "Something else", " ".join(f"other{i}" for i in range(300)))]
    e = SearchEngine.from_documents(docs, EngineConfig(encoder="lsa", lsa_dim=2, build_kg=False))
    assert e.dup_of == {1: 0}
    r = e.search("topic3 word5", mode="bm25", k=5)
    assert [h.doc_id for h in r.hits].count("b") == 0 and r.collapsed == 1 and r.hits[0].duplicates


def test_categorizer_rejects_when_unsure():
    from searchbridge.mining.categorize import Categorizer
    from searchbridge.text.preprocess import Analyzer
    an = Analyzer()
    texts = [f"neural network training gradient layer {i}" for i in range(20)] + [f"database query transaction index {i}" for i in range(20)]
    labels = ["Machine Learning"] * 20 + ["Databases"] * 20
    c = Categorizer(an, min_per_class=5).fit(texts, labels)
    assert c.ok and c.report["models"]["Multinomial Naive Bayes"]["accuracy"] >= 0.9
    assert c.predict("training a neural network layer by gradient")[0] == "Machine Learning"
    assert c.predict("medieval poetry and harvest festivals") is None


# ------------------------------------------------------------------ API: users never mixed
def test_api_memory_is_per_browser(tmp_path, monkeypatch, cran):
    from fastapi.testclient import TestClient
    import app.server as S
    monkeypatch.setattr(S, "STORE", InteractionStore(tmp_path / "api.db"))
    S._profiles.clear()
    e, Q, _ = cran
    monkeypatch.setitem(S.COLLECTIONS["cranfield"].__dict__, "engine", e)
    monkeypatch.setitem(S.COLLECTIONS["cranfield"].__dict__, "status", "ready")
    alice, bob = TestClient(S.app), TestClient(S.app)
    r = alice.get("/api/search", params={"c": "cranfield", "q": "wing flutter"}).json()
    target = r["hits"][7]["doc_id"]
    for _ in range(3):
        assert alice.post("/api/events", json={"c": "cranfield", "kind": "open", "doc": target, "q": "wing flutter"}).json()["recorded"]
        alice.post("/api/events", json={"c": "cranfield", "kind": "dwell", "doc": target, "q": "wing flutter", "value": 90})
    assert alice.post("/api/events", json={"c": "cranfield", "kind": "open", "doc": "nope"}).status_code == 404
    assert alice.post("/api/events", json={"c": "cranfield", "kind": "search"}).status_code == 422
    ra = [h["doc_id"] for h in alice.get("/api/search", params={"c": "cranfield", "q": "flutter of wings"}).json()["hits"]]
    rb = bob.get("/api/search", params={"c": "cranfield", "q": "flutter of wings"}).json()
    assert rb["memory"]["active"] is False and not any(h["personal"] for h in rb["hits"])
    if target in ra and target in [h["doc_id"] for h in rb["hits"]]:
        assert ra.index(target) <= [h["doc_id"] for h in rb["hits"]].index(target)
    me = alice.get("/api/me", params={"c": "cranfield"}).json()
    assert me["useful"][0]["id"] == target and "You opened it 3 times" in me["useful"][0]["reasons"]
    assert bob.get("/api/me", params={"c": "cranfield"}).json()["useful"] == []
    assert alice.get("/api/suggest", params={"c": "cranfield", "q": "wing"}).json()["history"] == ["wing flutter"]
    assert bob.get("/api/suggest", params={"c": "cranfield", "q": "wing"}).json()["popular"] == []   # k-anonymity
    assert alice.delete("/api/me/history").json()["deleted"] > 0
    assert alice.get("/api/me", params={"c": "cranfield"}).json()["useful"] == []


def test_crawl_output_format(tmp_path):
    p = tmp_path / "p.jsonl.gz"
    with gzip.open(p, "wt") as f:
        f.write(json.dumps({"id": "u1", "title": "T", "text": "x", "links": ["u2"], "type": "Web page"}) + "\n")
    d = load_jsonl(p)[0]
    assert d.links == ["u2"] and d.meta["type"] == "Web page"


def test_partial_matches_are_reported_honestly(cran):
    e, _, _ = cran
    r = e.search("flutter accidents", mode="smart", k=5, spell=False)
    c = r.coverage
    assert c["terms"] == ["flutter", "accidents"] and c["all"] <= c["any"] == r.total_matches
    if c["all"] == 0:
        assert all(h.missing for h in r.hits)
    full = e.search("wing flutter", mode="smart", k=3)
    assert full.coverage["all"] > 0 and not full.hits[0].missing


def test_incomplete_boolean_queries_are_repaired_not_rejected(cran):
    from searchbridge.retrieval.boolean import repair
    assert repair("wing AND") == "wing" and repair("( wing flutter") == "( wing flutter )"
    assert repair('"boundary layer') == '"boundary layer"'
    e, _, _ = cran
    for q in ["wing AND", "flutter OR", "( wing flutter", "wing AND (flutter"]:
        r = e.search(q, k=5)
        assert r.hits and r.notice, q


def test_long_pages_cut_mid_word_still_build():
    # regression: topic labelling divided by the frequency of a word fragment created by truncation
    docs = [Document(f"d{i}", f"Page {i}", ("information retrieval ranking " * 200) + f"relationship{i} " * 3) for i in range(12)]
    e = SearchEngine.from_documents(docs, EngineConfig(encoder="lsa", lsa_dim=4, build_kg=False))
    assert e.topic_labels and e.search("ranking", k=3).hits


def test_html_extraction_keeps_article_and_drops_menus():
    from searchbridge.documents import parse_html
    page = ('<html><title>PageRank - Wikipedia</title><body><nav><a href="/wiki/Main_Page">Main page</a> Toggle the table of contents</nav>'
            '<div class="vector-sidebar">Move to sidebar hide</div><main id="content"><h1>PageRank</h1>'
            '<div id="mw-content-text"><p>PageRank ranks web pages by their <a href="/wiki/Hyperlink">links</a>.<sup>[1]</sup></p>'
            '<h2>History<span class="mw-editsection">[edit]</span></h2><p>' + "Citation analysis came first. " * 10 + '</p>'
            '<div class="navbox"><a href="/wiki/Bing">Bing</a></div></div></main><footer>Privacy policy</footer></body></html>')
    title, text, links = parse_html(page)
    assert title == "PageRank - Wikipedia" and "ranks web pages" in text and "History Citation" in text
    for junk in ("Toggle", "sidebar", "[edit]", "[1]", "Privacy", "Bing", "Main page"):
        assert junk not in text, junk
    assert links == ["/wiki/Hyperlink"]


def test_bridge_uses_semantic_only_evidence_and_skips_empty_query_vectors(cran, monkeypatch):
    engine, _, _ = cran
    query = "qzxvplm"
    for mode in ("bridge", "smart"):
        response = engine.search(query, mode=mode, spell=False)
        assert not response.hits and not response.expansion_terms

    vector = engine.dense.query_vector("wing flutter")
    monkeypatch.setattr(engine.dense, "query_vector", lambda text: vector)
    scores, parts = engine.bridge.score(engine.analyzer(query), query, return_parts=True)
    assert not parts["L0"] and parts["feedback"] and scores


def test_crawl_link_count_matches_exported_edges(tmp_path):
    from scripts.crawl_web import crawl

    seed = "https://example.org/a"
    pages = {seed: '<title>Greenhouse gardening</title><a href="/a">self</a><a href="/b">trees</a><a href="/b">again</a>',
             "https://example.org/b": "<title>Orchard trees</title>Apples and pears need water and sunlight."}
    output = tmp_path / "pages.jsonl.gz"
    stats = crawl([seed], out=output, delay=0, fetch=lambda url: (200, "text/html", pages[url]),
                  robots_fetch=lambda url: "", log=lambda *args: None)
    docs = load_jsonl(output)
    saved = json.loads((tmp_path / "crawl_stats.json").read_text())
    assert len(docs) == 2 and docs[0].links == ["https://example.org/b"] and docs[1].links == []
    assert stats["links"] == saved["links"] == sum(len(doc.links) for doc in docs) == 1


def test_topic_labels_handle_excerpt_boundaries_and_abstract_only_words():
    docs = []
    for i in range(8):
        if i < 4:
            # The old 2,500-character excerpt ended in "phot" inside "photometry".
            text = "orbit " * 416 + "photometry measurements"
            docs.append(Document(str(i), "Stars", text))
        else:
            docs.append(Document(str(i), "Trees", "forest roots soil",
                                 {"abstract": "canopy canopy canopy"}))

    engine = SearchEngine.from_documents(docs, EngineConfig(encoder="lsa", n_topics=2, build_kg=False))
    labels = " ".join(engine.topic_labels.values()).lower().split()
    assert "canopy" in labels and "phot" not in labels
    assert len(engine.doc_topic) == len(docs)
    assert engine.search("photometry", mode="bm25").hits
