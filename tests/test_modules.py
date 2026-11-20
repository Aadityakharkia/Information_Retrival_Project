"""Unit tests: mining, link analysis, crawler, semantic layer, responsible IR, engine end-to-end."""
from pathlib import Path

import numpy as np
import pytest

from searchbridge.documents import load_directory, parse_html
from searchbridge.engine import EngineConfig, SearchEngine
from searchbridge.mining.classify import KNNClassifier, MultinomialNB, RocchioClassifier
from searchbridge.mining.cluster import KMeans, hac, nmi, purity, rand_index
from searchbridge.responsible.credibility import credibility
from searchbridge.responsible.fairness import exposure_by_group, fair_rerank, mmr
from searchbridge.responsible.privacy import QueryLog, find_pii, redact
from searchbridge.semantic.entities import CollocationMiner, Concept, Ontology, pattern_ner
from searchbridge.text.preprocess import Analyzer
from searchbridge.web.crawler import CrawlConfig, Crawler, MinHasher, jaccard, shingles
from searchbridge.web.linkanalysis import adjacency, hits, pagerank

ROOT = Path(__file__).resolve().parents[1]


def test_naive_bayes_iir_example():
    # IIR Example 13.1: China vs not-China
    an = Analyzer(); an.config = an.config.__class__(stem=False, remove_stopwords=False)
    nb = MultinomialNB(an).fit(["Chinese Beijing Chinese", "Chinese Chinese Shanghai", "Chinese Macao", "Tokyo Japan Chinese"],
                               ["china", "china", "china", "not"])
    assert nb.predict("Chinese Chinese Chinese Tokyo Japan") == "china"
    p = nb.predict_proba("Chinese Chinese Chinese Tokyo Japan")
    c = 3 / 4 * (3 / 7) ** 3 * (1 / 14) ** 2      # exact values behind IIR's rounded 0.0003
    n = 1 / 4 * (2 / 9) ** 3 * (2 / 9) ** 2         # ... and 0.0001
    assert p["china"] == pytest.approx(c / (c + n))


def test_vector_classifiers():
    X = ["wing lift drag", "lift wing airfoil", "heat transfer wall", "wall heat flux"]
    y = ["aero", "aero", "heat", "heat"]
    an = Analyzer()
    for clf in (RocchioClassifier(an).fit(X, y), KNNClassifier(an, 1).fit(X, y)):
        assert clf.predict("airfoil lift") == "aero" and clf.predict("heat flux") == "heat"


def test_clustering_and_measures():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal([5, 0], 0.3, (20, 2)), rng.normal([0, 5], 0.3, (20, 2))])
    gold = ["a"] * 20 + ["b"] * 20
    lab = KMeans(2, seed=1).fit(X).labels_
    assert purity(list(lab), gold) == 1.0 and nmi(list(lab), gold) == pytest.approx(1.0)
    assert purity(list(hac(X, 2, "average")[0]), gold) == 1.0
    assert rand_index([0, 0, 1, 1], ["x", "x", "y", "y"]) == 1.0


def test_pagerank_and_hits():
    A = adjacency(3, [(0, 1), (1, 2), (2, 0), (0, 2)])
    pr = pagerank(A)
    assert pr.sum() == pytest.approx(1.0) and pr.argmax() == 2
    A2 = adjacency(4, [(0, 3), (1, 3), (2, 3)])   # 3 is the authority, dangling
    h, a = hits(A2)
    assert a.argmax() == 3 and h[3] == pytest.approx(0)
    assert pagerank(A2).sum() == pytest.approx(1.0)


def test_crawler_offline():
    body = " ".join(f"word{i}" for i in range(80))
    site = {"http://x.org/": '<a href="/a">a</a><a href="/b">b</a><a href="/private/p">p</a>',
            "http://x.org/a": "<title>A</title>" + body,
            "http://x.org/b": "<title>B</title>" + body,
            "http://x.org/private/p": "secret"}
    fetch = lambda u: (200, "text/html", site[u]) if u in site else (404, "", "")
    cr = Crawler(CrawlConfig(max_pages=10, delay_s=0), fetch=fetch, robots_fetch=lambda u: "User-agent: *\nDisallow: /private")
    docs = cr.crawl(["http://x.org/"])
    urls = {d.doc_id for d in docs}
    assert "http://x.org/private/p" not in urls and cr.stats["robots_blocked"] == 1
    assert cr.stats["dup_exact"] + cr.stats["dup_near"] == 1   # a and b are duplicates


def test_minhash_estimates_jaccard():
    a = shingles("the quick brown fox jumps over the lazy dog again and again", 2)
    b = shingles("the quick brown fox jumps over the lazy cat again and again", 2)
    mh = MinHasher(256)
    assert abs(MinHasher.similarity(mh.signature(a), mh.signature(b)) - jaccard(a, b)) < 0.15


def test_html_parse():
    t, txt, links = parse_html("<html><title>T</title><script>x=1</script><p>Hello &amp; bye</p><a href='/a'>a</a></html>")
    assert t == "T" and "x=1" not in txt and "Hello & bye" in txt and links == ["/a"]


def test_entities_and_ontology():
    ms = pattern_ner("NASA tested the NACA 0012 airfoil at Langley Research Center in 1958.")
    labels = {m.text: m.label for m in ms}
    assert labels.get("NACA 0012") == "CODE" and labels.get("NASA") == "ACRONYM" and labels.get("1958") == "YEAR"
    onto = Ontology([Concept("jaguar_car", "jaguar", ["jaguar cars"], description="car vehicle engine luxury"),
                     Concept("jaguar_cat", "jaguar", ["panthera onca"], description="cat animal jungle predator")])
    assert onto.link("the jaguar hunted in the jungle as a predator")[0].concept == "jaguar_cat"
    assert onto.link("the jaguar engine is a luxury car")[0].concept == "jaguar_car"
    cm = CollocationMiner(min_count=2).fit(["boundary layer flow", "the boundary layer", "boundary layer heat"] * 2)
    assert "boundary layer" in cm.phrases


def test_privacy():
    t = "mail a.b@x.com, call +91 98765 43210, card 4111 1111 1111 1111, PAN ABCDE1234F"
    kinds = {k for k, _ in find_pii(t)}
    assert {"EMAIL", "PHONE", "CARD", "PAN"} <= kinds
    r = redact(t)
    assert "a.b@x.com" not in r and "4111" not in r and "[EMAIL]" in r
    log = QueryLog(k_anonymity=2)
    for u in ("u1", "u2"):
        log.log(u, "wing flutter")
    log.log("u3", "my secret query")
    assert log.releasable_queries() == {"wing flutter": 2}


def test_credibility_and_fairness():
    good = credibility("Results suggest a 12% drag reduction (Smith et al., 2019) [3]. doi:10.1000/xyz", "https://arxiv.org/abs/1")
    bad = credibility("SHOCKING!!! You won't believe this miracle cure, ALWAYS works, 100% guaranteed!!!")
    assert good.score > 0.6 and bad.flag == "low-credibility"
    emb = np.eye(4)
    emb[1] = emb[0]
    out = mmr([(0, 1.0), (1, 0.99), (2, 0.5), (3, 0.4)], emb, lam=0.5, k=2)
    assert [d for d, _ in out] == [0, 2]          # duplicate of 0 is skipped
    group = {0: "A", 1: "A", 2: "A", 3: "B"}.get
    fr = fair_rerank([(0, 1.0), (1, 0.95), (2, 0.9), (3, 0.85)], group, k=3, tradeoff=0.8)
    assert 3 in [d for d, _ in fr]
    assert sum(exposure_by_group([0, 1, 3], group).values()) == pytest.approx(1.0)


@pytest.fixture(scope="module")
def engine():
    return SearchEngine.from_documents(load_directory(ROOT / "data/sample"), EngineConfig(lsa_dim=5))


def test_engine_end_to_end(engine, tmp_path):
    r = engine.search("relevence feedback vocabulary mismatch", k=3)
    assert r.corrected_query and r.hits[0].doc_id == "query_expansion.txt"
    assert engine.search('"gap encoding" AND compress*', mode="boolean").hits[0].doc_id == "index_compression.html"
    assert engine.search("miracle", mode="bm25").hits[0].flags == ["low-credibility"]
    filtered = engine.search("ranking type:md", k=10).hits
    assert filtered and all(h.doc_id.endswith(".md") for h in filtered)
    assert "citation" in engine.graph_kind
    rel = engine.related_documents("pagerank.md", 2)
    assert len(rel) == 2 and set(rel[0][3]) == {"semantic", "lexical", "entities", "graph"}
    for m in ("bm25", "tfidf", "lm", "sdm", "dense", "hybrid", "rrf", "adaptive", "bridge"):
        assert engine.search("ranking evaluation", mode=m, k=3).hits
    p = tmp_path / "e.pkl"; engine.save(p)
    assert SearchEngine.load(p).search("pagerank").hits[0].doc_id == "pagerank.md"


def test_engine_add_document(engine):
    from searchbridge.documents import Document
    engine.add_document(Document("new.txt", "Learning to rank", "LambdaMART learning to rank gradient boosted trees"))
    assert engine.search("lambdamart", mode="bm25").hits[0].doc_id == "new.txt"
    assert engine.search("lambdamart gradient boosted", mode="bridge").hits[0].doc_id == "new.txt"
