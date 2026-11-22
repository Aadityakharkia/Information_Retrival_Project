"""SearchBridge AI — the search engine facade that wires every module together.

    engine = SearchEngine.from_documents(load_directory("my_pdfs/"))
    resp = engine.search("boundary layer heat transfer", mode="bridge", k=10)
    for hit in resp.hits: print(hit.rank, hit.title, hit.score)
"""
from __future__ import annotations

import logging
import math
import os
import pickle
import re
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .documents import Document
from .index.inverted_index import InvertedIndex
from .index.kgram import KGramIndex
from .mining.categorize import Categorizer, topical
from .mining.cluster import KMeans, hac
from .personal import rerank as personal_rerank
from .personal.rerank import PersonalContext
from .query.feedback import AssociationThesaurus, rocchio
from .responsible.credibility import credibility
from .responsible.fairness import fair_rerank, mmr
from .responsible.privacy import QueryLog, redact
from .retrieval.adaptive import AdaptiveHybrid, AdaptiveModel
from .retrieval.boolean import BooleanRetriever, looks_boolean, repair as repair_boolean
from .retrieval.bridge_prf import BridgePRF, BridgePRFConfig
from .retrieval.fusion import interpolate, rrf
from .retrieval.lexical import BM25Retriever, LMRetriever, SDMRetriever, TFIDFRetriever, top_k
from .retrieval.qpp import QPP
from .retrieval.semantic import DenseRetriever, make_encoder
from .semantic.entities import CollocationMiner, Ontology
from .semantic.knowledge_graph import KnowledgeGraph
from .snippets import highlight, snippet
from .suggest import Suggester
from .text.preprocess import STOPWORDS, Analyzer, PreprocessConfig, tokenize
from .web.crawler import LSHIndex, MinHasher, jaccard, shingles
from .web.linkanalysis import hits, links_to_graph, pagerank_v1, pagerank_v2, pagerank_v3
from scipy import sparse

log = logging.getLogger(__name__)

MODES = ["smart", "bridge", "adaptive", "hybrid", "rrf", "bm25", "tfidf", "lm", "sdm", "dense", "boolean"]
MODE_INFO = {
    "smart": ("Smart", "Bridge-PRF relevance + link authority (PageRank, HITS) + your search memory, with near-duplicates collapsed"),
    "bridge": ("Bridge-PRF", "Ours: hybrid lexical + semantic retrieval with shared pseudo-relevance feedback"),
    "adaptive": ("Adaptive hybrid", "Ours: per-query fusion weight predicted from query-performance signals"),
    "hybrid": ("Hybrid", "Min-max normalised BM25 ⊕ semantic scores"),
    "rrf": ("RRF", "Reciprocal Rank Fusion of BM25 and semantic rankings"),
    "bm25": ("BM25", "Okapi BM25 probabilistic model"),
    "tfidf": ("TF-IDF", "Vector space model, lnc.ltc cosine"),
    "lm": ("Language model", "Query likelihood with Dirichlet smoothing"),
    "sdm": ("MRF / SDM", "Markov random field: unigrams + ordered & unordered term pairs"),
    "dense": ("Semantic", "Embedding cosine similarity only"),
    "boolean": ("Boolean", "Exact AND / OR / NOT, \"phrases\"~k and wild*cards"),
}
FACET_FIELDS = ("category", "type", "topic", "venue")
_FIELD_RE = re.compile(r'\b(\w+):("[^"]+"|\S+)')
_FILTER_FIELDS = {"author", "type", "source", "year", "category", "venue", "topic", "tag"}


@dataclass
class Hit:
    rank: int
    doc_id: str
    title: str
    score: float
    snippet: str
    snippet_html: str
    credibility: float
    flags: List[str] = field(default_factory=list)
    explanation: List[Tuple[str, int, float, float]] = field(default_factory=list)
    meta: Dict[str, str] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    topic: str = ""
    credibility_reasons: List[Tuple[str, float]] = field(default_factory=list)
    words: int = 0
    signal: Dict[str, float] = field(default_factory=dict)   # share of evidence: lexical vs semantic
    breakdown: Dict[str, float] = field(default_factory=dict)  # smart mode: additive score components
    personal: List[str] = field(default_factory=list)          # why your history moved this result
    duplicates: List[Dict[str, str]] = field(default_factory=list)  # near-identical documents folded into this hit
    category: str = ""
    missing: List[str] = field(default_factory=list)            # query words this document does not contain


@dataclass
class SearchResponse:
    query: str
    mode: str
    hits: List[Hit]
    total_matches: int
    took_ms: float
    corrected_query: Optional[str] = None
    expansion_terms: List[Tuple[str, float]] = field(default_factory=list)
    related_concepts: List[Tuple[str, float]] = field(default_factory=list)
    alpha: Optional[float] = None
    facets: Dict[str, List[Tuple[str, int]]] = field(default_factory=dict)
    offset: int = 0
    filters: Dict[str, str] = field(default_factory=dict)
    intent: Optional[Tuple[str, float]] = None       # query category predicted by the classifiers
    context_used: Optional[str] = None               # earlier query used as context
    personalized: int = 0                            # results whose position your history changed
    collapsed: int = 0                               # near-duplicates folded into other results
    coverage: Dict[str, object] = field(default_factory=dict)   # how many documents contain the query words
    notice: str = ""                                 # e.g. an incomplete Boolean query that was repaired


@dataclass
class EngineConfig:
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    encoder: str = "lsa"            # "lsa" | "sbert" | "auto"
    lsa_dim: int = 200
    bm25_k1: float = 1.2
    bm25_b: float = 0.75
    hybrid_alpha: float = 0.3
    bridge: BridgePRFConfig = field(default_factory=BridgePRFConfig)
    build_kg: bool = True
    ontology_path: Optional[str] = None
    adaptive_model_path: Optional[str] = None
    n_topics: Optional[int] = None  # None = automatic


def _title_case_phrase(p: str) -> str:
    return " ".join(w if w.isupper() else w[:1].upper() + w[1:] for w in p.split())


class SearchEngine:
    def __init__(self, docs: List[Document], config: Optional[EngineConfig] = None):
        self.cfg = config or EngineConfig()
        self.docs = docs
        self.analyzer = Analyzer(self.cfg.preprocess)
        self.query_log = QueryLog()
        self._cache: "OrderedDict[tuple, SearchResponse]" = OrderedDict()

    # ------------------------------------------------------------------ build
    @classmethod
    def from_documents(cls, docs: List[Document], config: Optional[EngineConfig] = None) -> "SearchEngine":
        if not docs:
            raise ValueError("no documents to index")
        eng = cls(docs, config)
        eng._build()
        return eng

    def _build(self) -> None:
        t0 = time.time()
        c = self.cfg
        texts = [d.full_text for d in self.docs]
        self.index = InvertedIndex(self.analyzer).build((d.doc_id, t) for d, t in zip(self.docs, texts))
        self.kgram = KGramIndex().build(t for x in texts for t in tokenize(x))
        self.surface: Dict[str, str] = {}   # stem -> most frequent surface word (for display)
        for w, _ in self.kgram.freq.most_common():
            self.surface.setdefault(self.analyzer.analyze_term(w) or w, w)
        self.bm25 = BM25Retriever(self.index, c.bm25_k1, c.bm25_b)
        self.tfidf = TFIDFRetriever(self.index)
        self.lm = LMRetriever(self.index, "dirichlet", mu=300)
        self.sdm = SDMRetriever(self.index, mu=300)
        self.boolean = BooleanRetriever(self.index, self.kgram.wildcard)
        self.dense = DenseRetriever(make_encoder(c.encoder, self.analyzer, dim=c.lsa_dim), texts)
        self.bridge = BridgePRF(self.bm25, self.dense, c.bridge)
        model = AdaptiveModel.load(c.adaptive_model_path) if c.adaptive_model_path and Path(c.adaptive_model_path).exists() else None
        self.adaptive = AdaptiveHybrid(QPP(self.index), model)
        self._build_graph()
        self._thesaurus: Optional[AssociationThesaurus] = None
        self.kg: Optional[KnowledgeGraph] = None
        self.phrases: Counter = Counter()
        for d in self.docs:
            self.phrases.update({t.lower() for t in d.tags})
        # short "summary" view (title + abstract or opening text): avoids reference lists and
        # boilerplate dominating phrase mining, topics and the knowledge graph
        summaries = []
        for d in self.docs:
            excerpt = d.meta.get("abstract")
            if not excerpt:
                excerpt = d.text[:2500]
                if len(d.text) > 2500 and not d.text[2500].isspace():
                    excerpt = re.sub(r"\S+$", "", excerpt)
            summaries.append(f"{d.title}. {excerpt}")
        if c.build_kg:
            onto = Ontology.load(c.ontology_path) if c.ontology_path and Path(c.ontology_path).exists() else None
            miner = CollocationMiner(min_count=max(3, len(self.docs) // 400)).fit(summaries)
            self.kg = KnowledgeGraph(onto, miner).build(summaries, doc_tags=[d.tags for d in self.docs])
            for p in miner.phrases:
                self.phrases[p] += len(self.kg.entity_docs.get(p, ())) or 1
        self.cred = [credibility(d.text[:20000], d.meta.get("source", ""), float(self.pagerank[i]))
                     for i, d in enumerate(self.docs)]
        self._build_topics(summaries)
        self._build_duplicates()
        self._build_categories(summaries)
        self.suggester = Suggester(self)
        self.build_seconds = time.time() - t0
        log.info("Indexed %d docs in %.1fs", len(self.docs), self.build_seconds)

    def _build_graph(self) -> None:
        """Link graph from real citations / hyperlinks only (never synthesised from text similarity).
        PageRank V1, V2 and V3 are all computed so they can be compared; V3 is the one used for ranking."""
        n = len(self.docs)
        links = [d.links for d in self.docs]
        L = links_to_graph(links, self.index.doc_index) if any(links) else sparse.csr_matrix((n, n))
        self.link_graph = L.tocsr()
        self.link_in = L.T.tocsr()
        self.n_links = int(L.nnz)
        linked = (np.diff(self.link_graph.indptr) > 0) | (np.diff(self.link_in.indptr) > 0)
        self.link_coverage = float(linked.mean()) if n else 0.0     # share of documents with any link
        kinds = {d.meta.get("type", "") for d in self.docs if d.links}
        self.graph_kind = ("hyperlinks" if any("web" in k.lower() for k in kinds) else "citations") if self.n_links else "none"
        self.graph = self.link_graph
        self.pr_versions: Dict[str, Dict] = {}
        if self.n_links:
            for name, fn in (("v1", pagerank_v1), ("v2", pagerank_v2), ("v3", pagerank_v3)):
                r, it, hist = fn(L)
                self.pr_versions[name] = {"scores": r.astype(np.float32), "iterations": it, "mass": hist}
            pr = self.pr_versions["v3"]["scores"].astype(float)
            # rank authority by the log of PageRank relative to a page with no in-links, scaled to [0, 1]
            base = pr.min()
            self.pagerank = np.log(pr / base) / max(np.log(pr.max() / base), 1e-9) if pr.max() > base else np.zeros(n)
        else:
            self.pagerank = np.zeros(n)

    def out_links(self, d: int) -> Sequence[int]:
        return self.link_graph.indices[self.link_graph.indptr[d]:self.link_graph.indptr[d + 1]] if self.n_links and d < self.link_graph.shape[0] else []

    def in_links(self, d: int) -> Sequence[int]:
        return self.link_in.indices[self.link_in.indptr[d]:self.link_in.indptr[d + 1]] if self.n_links and d < self.link_in.shape[0] else []

    def hits_scores(self, cands: Sequence[int], root_size: int = 30, max_in: int = 50) -> Tuple[Dict[int, float], Dict[int, float], int]:
        """Kleinberg's HITS on the query's base set: root = top candidates, base = root + their link neighbours."""
        if not self.n_links:
            return {}, {}, 0
        root = list(cands[:root_size])
        base = set(root)
        for d in root:
            base.update(int(x) for x in self.out_links(d))
            base.update(int(x) for x in list(self.in_links(d))[:max_in])
        nodes = sorted(base)
        sub = self.link_graph[nodes][:, nodes]
        if sub.nnz == 0:
            return {}, {}, 0
        hub, auth = hits(sub)
        ma, mh = auth.max() or 1, hub.max() or 1
        return ({nodes[i]: float(auth[i] / ma) for i in range(len(nodes))},
                {nodes[i]: float(hub[i] / mh) for i in range(len(nodes))}, int(sub.nnz))

    def _build_duplicates(self, threshold: float = 0.8) -> None:
        """MinHash + LSH near-duplicate detection; duplicates are folded into one result at query time."""
        mh, lsh = MinHasher(64, seed=3), LSHIndex(bands=16, rows=4)
        sh = [shingles(f"{d.title} {d.text[:4000]}".lower()) for d in self.docs]
        self.dup_of: Dict[int, int] = {}
        self.dup_pairs: List[Tuple[int, int, float]] = []
        for i, s_ in enumerate(sh):
            if len(s_) < 5:
                lsh.add(mh.signature(s_ or {"empty"}))
                continue
            sig = mh.signature(s_)
            for j in lsh.candidates(sig):
                if j < i and len(sh[j]) >= 5:
                    jac = jaccard(s_, sh[j])
                    if jac >= threshold:
                        rep = self.dup_of.get(j, j)
                        self.dup_of[i] = rep
                        self.dup_pairs.append((j, i, round(jac, 3)))
                        break
            lsh.add(sig)

    def _build_categories(self, summaries: List[str]) -> None:
        labels = [d.meta.get("category", "") for d in self.docs]
        if any(d.meta.get("venue") and d.meta.get("venue") == d.meta.get("category") for d in self.docs[:50]):
            labels = [""] * len(self.docs)          # venue labels are not topics (e.g. Cranfield)
        self.categorizer = Categorizer(self.analyzer).fit(summaries, labels)
        self.doc_category = [lab if topical(lab) else "" for lab in labels]
        self.category_predicted = [False] * len(self.docs)
        if self.categorizer.ok:
            for i, lab in enumerate(self.doc_category):
                if not lab:
                    p = self.categorizer.predict(summaries[i])
                    if p:
                        self.doc_category[i], self.category_predicted[i] = p[0], True

    def _build_topics(self, summaries: List[str]) -> None:
        """Automatic topic facet: spherical k-means on document embeddings, labelled with
        distinctive keyphrases (tags) or, if none, distinctive words."""
        n = len(self.docs)
        k = self.cfg.n_topics or int(np.clip(round(math.sqrt(n / 10)), 2, 16))
        if n < 8:
            self.doc_topic = ["All documents"] * n
            self.topic_labels = {0: "All documents"}
            self.topic_centroids = self.dense.emb.mean(0, keepdims=True)
            return
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        X = TfidfVectorizer(analyzer=self.analyzer, sublinear_tf=True, min_df=2 if n > 50 else 1).fit_transform(
            [f"{s} {' '.join(d.tags) * 2}" for s, d in zip(summaries, self.docs)])
        Z = TruncatedSVD(min(100, X.shape[1] - 1, n - 1), random_state=0).fit_transform(X) if X.shape[1] > 2 else X.toarray()
        lab = KMeans(k, n_init=3, seed=0).fit(Z).labels_
        global_tags: Counter = Counter()
        casing: Dict[str, str] = {}
        for d in self.docs:
            global_tags.update({t.lower() for t in d.tags})
            for t in d.tags:
                if t != t.lower():
                    casing.setdefault(t.lower(), t)
        # Score cluster words against the same summary corpus, including metadata abstracts.
        cluster_words = [Counter() for _ in range(k)]
        label_words = self.surface.copy()
        for cluster, summary in zip(lab, summaries):
            words = Counter(tokenize(summary, self.cfg.preprocess.split_hyphens))
            for word, frequency in words.items():
                term = self.analyzer.analyze_term(word)
                if term:
                    cluster_words[cluster][term] += frequency
                    label_words.setdefault(term, word)
        cf: Counter = Counter()
        for counts in cluster_words:
            cf.update(counts)
        total = sum(cf.values())
        labels: Dict[int, str] = {}
        used: set = set()
        for c in range(k):
            members = [i for i in range(n) if lab[i] == c]
            tagc: Counter = Counter()
            for i in members:
                tagc.update({t.lower() for t in self.docs[i].tags})
            cands = [(cnt * math.log(n / global_tags[t]), t) for t, cnt in tagc.items() if cnt >= 2 and len(t.split()) <= 3]
            if not cands:   # distinctive words: cluster tf vs collection tf
                ctf = cluster_words[c]
                ct = sum(ctf.values())
                cands = [(v / ct * math.log((v / ct) / (cf[w] / total) + 1e-9), label_words[w])
                         for w, v in ctf.items() if v >= 2 and len(w) > 2 and label_words[w] not in STOPWORDS]
            picked = []
            for _, t in sorted(cands, reverse=True):
                if t not in used and not any(t in p or p in t for p in picked):
                    picked.append(t)
                if len(picked) == 2:
                    break
            used.update(picked)
            labels[c] = " & ".join(_title_case_phrase(casing.get(p, p)) for p in picked) or f"Topic {c + 1}"
        self.topic_labels = labels
        self.doc_topic = [labels[int(c)] for c in lab]
        emb = self.dense.emb
        self.topic_centroids = np.vstack([emb[lab == c].mean(0) if (lab == c).any() else np.zeros(emb.shape[1]) for c in range(k)])

    @property
    def thesaurus(self) -> AssociationThesaurus:
        if self._thesaurus is None:
            self._thesaurus = AssociationThesaurus(self.index)
        return self._thesaurus

    # ------------------------------------------------------------------ query parsing
    def parse(self, query: str) -> Tuple[str, Dict[str, str], List[str]]:
        """Strip field filters (author:smith type:pdf) and return (free_text, filters, phrases)."""
        filters = {}
        for m in _FIELD_RE.finditer(query):
            if m.group(1).lower() in _FILTER_FIELDS:
                filters[m.group(1).lower()] = m.group(2).strip('"').lower()
        free = _FIELD_RE.sub(lambda m: "" if m.group(1).lower() in _FILTER_FIELDS else m.group(0), query).strip()
        phrases = re.findall(r'"([^"]+)"', free)
        return free, filters, phrases

    def _field(self, d: int, key: str) -> str:
        if key == "topic":
            return self.doc_topic[d]
        if key == "category" and hasattr(self, "doc_category") and d < len(self.doc_category):
            return self.doc_category[d]
        if key == "tag":
            return " | ".join(self.docs[d].tags)
        return str(self.docs[d].meta.get(key, ""))

    def _passes(self, d: int, filters: Dict[str, str]) -> bool:
        for k, v in filters.items():
            val = self._field(d, k).lower()
            if k == "tag":
                if v.lower() not in [t.lower() for t in self.docs[d].tags]:
                    return False
            elif v.lower() not in val:
                return False
        return True

    CONTEXT_TOP, CONTEXT_LIFT = 0.02, 3.0

    def _context_related(self, context: str, scores: Dict[int, float], depth: int = 200) -> bool:
        """Is the earlier query about something this query's results contain? Comparing two short queries
        directly is too noisy (related pairs score 0.04-0.43, unrelated ones up to 0.22 with SBERT), so instead
        count how many of this query's top `depth` candidates are among the 2 % of the collection closest to the
        earlier query; the context is used when that share is at least 3x what chance gives. Relative to the
        collection, so it works the same for SBERT and LSA, and it also catches a minority sense
        ("attacks" after "wireless sensor network routing")."""
        ids = [d for d, _ in top_k(scores, depth)]
        if not ids:
            return False
        cs = self.dense.emb @ self.dense.query_vector(context)
        threshold = float(np.quantile(cs, 1 - self.CONTEXT_TOP))
        return float((cs[ids] >= threshold).mean()) >= self.CONTEXT_LIFT * self.CONTEXT_TOP

    _GIBBERISH = ("qwzxv plmkj", "asdf ghjk", "zzkq vvbn", "pqowie ruty")

    def _noise_floor(self) -> float:
        """Best document similarity that random letter strings reach with this encoder: sentence encoders
        map any input somewhere in the space, so a nonsense query always has a "closest" document."""
        if getattr(self, "_noise", None) is None:
            self._noise = max(float((self.dense.emb @ self.dense.query_vector(g)).max()) for g in self._GIBBERISH)
        return self._noise

    def _nothing_matches(self, q_terms: Sequence[str], text: str) -> bool:
        """No query word occurs in the collection and the meaning match is no better than gibberish."""
        if any(self.index.df(t) for t in q_terms):
            return False
        best = float((self.dense.emb @ self.dense.query_vector(text)).max()) if len(self.dense.emb) else 0.0
        return best <= self._noise_floor() + 0.05

    def _correct_word(self, w: str) -> str:
        """Correct only words that look like typos. A word is left alone when it is in the collection, when it is
        short (short words have too many one-letter neighbours: stop -> step), when the candidate just adds or
        removes an affix (orthodox -> unorthodox), or when its stem is indexed and the candidate has a different
        stem (efficiently -> sufficiently would change the search). One edit below 10 letters, two from 10 on
        (two edits on shorter words turn real words into others: learning -> leading)."""
        if w in self.kgram.freq or not w.isalpha() or len(w) <= 5:
            return w
        t = self.analyzer.analyze_term(w)
        if not t:
            return w
        cands = self.kgram.suggest(w, max_dist=1 if len(w) < 10 else 2)
        if not cands:
            return w
        f = cands[0][0]
        if w in f or f in w:
            return w
        if t in self.index.postings:      # a real word (efficiently, invert): only fix pure misspellings of
            # the same stem (relevence -> relevance), not inflections that differ only in the ending
            same_stem = self.analyzer.analyze_term(f) == t
            inflection = len(os.path.commonprefix([w, f])) >= min(len(w), len(f)) - 2
            return f if same_stem and not inflection else w
        return f

    def _spell_correct(self, free: str) -> str:
        """Fix typos word by word inside the original text, so quotes, wildcards and punctuation survive."""
        def fix_word(m: re.Match) -> str:
            word = m.group(0)
            fixed = self._correct_word(word.lower())
            return word if fixed == word.lower() else fixed

        def fix_token(m: re.Match) -> str:
            tok = m.group(0)
            if "*" in tok or "?" in tok.rstrip("?") or ":" in tok:
                return tok
            return re.sub(r"[A-Za-z]+", fix_word, tok)
        return re.sub(r"\S+", fix_token, free)

    def _expand_wildcards(self, text: str) -> str:
        out = []
        for w in text.split():
            w = w.rstrip("?")                  # a question mark ending a question is punctuation, not a wildcard
            out.append(" ".join(self.kgram.wildcard(w.lower(), 5)) if ("*" in w or "?" in w) else w)
        return " ".join(out)

    # ------------------------------------------------------------------ main entry point
    def search(self, query: str, mode: str = "bridge", k: int = 10, spell: bool = True,
               diversify: bool = False, mmr_lambda: float = 0.7, pagerank_weight: float = 0.0,
               fair_group: Optional[str] = None, explain: bool = True, user: str = "anonymous",
               filters: Optional[Dict[str, str]] = None, offset: int = 0, personal: Optional[PersonalContext] = None,
               context: str = "", dedupe: bool = True) -> SearchResponse:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        key = (query, mode, k, spell, diversify, mmr_lambda, pagerank_weight, fair_group, explain,
               tuple(sorted((filters or {}).items())), offset, personal.key if personal else "", context, dedupe)
        self.query_log.log(user, query)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        resp = self._search(query, mode, k, spell, diversify, mmr_lambda, pagerank_weight, fair_group, explain, filters, offset,
                            personal, context, dedupe)
        self._cache[key] = resp
        if len(self._cache) > 256:
            self._cache.popitem(last=False)
        return resp

    def _search(self, query, mode, k, spell, diversify, mmr_lambda, pagerank_weight, fair_group, explain, extra_filters, offset,
                personal=None, context="", dedupe=True):
        t0 = time.time()
        free, filters, phrases = self.parse(query)
        filters.update({kk: vv for kk, vv in (extra_filters or {}).items() if vv})
        corrected = None
        notice = ""
        requested = mode
        if mode != "boolean" and looks_boolean(free):
            mode = "boolean"
        if mode == "boolean":
            try:
                self.boolean.parser.parse(free)
            except ValueError as ex:
                fixed_q = repair_boolean(free)
                try:
                    self.boolean.parser.parse(fixed_q)
                    notice = f"Incomplete Boolean query ({ex}); searched for {fixed_q} instead."
                    free = fixed_q
                except ValueError:
                    free = re.sub(r"\b(AND|OR|NOT)\b|[()]", " ", free).strip()
                    notice = f"Could not read this as a Boolean query ({ex}); ranked by relevance instead."
                    mode = requested if requested != "boolean" else "bm25"
        if spell and mode != "boolean":
            fixed_free = self._spell_correct(free)
            if fixed_free != free:
                corrected = free = fixed_free
        text = self._expand_wildcards(free.replace('"', ""))
        q_terms = self.analyzer(text)
        alpha = None
        expansion: List[Tuple[str, float]] = []
        breakdown: Dict[int, Dict[str, float]] = {}
        reasons: Dict[int, List[str]] = {}
        context_used = None
        intent = self.categorizer.query_intent(text) if getattr(self, "categorizer", None) and q_terms else None

        if not q_terms and mode != "boolean" and not filters:
            return SearchResponse(query, mode, [], 0, round((time.time() - t0) * 1000, 1), corrected, filters=filters)
        if q_terms and mode != "boolean" and self._nothing_matches(q_terms, text):
            return SearchResponse(query, mode, [], 0, round((time.time() - t0) * 1000, 1), corrected, filters=filters,
                                  notice="No document contains these words or anything close in meaning.")
        if not q_terms and mode != "boolean":     # filter-only browse: rank by PageRank
            scores = {i: float(self.pagerank[i]) for i in range(len(self.docs))}
        elif mode == "boolean":
            matched = self.boolean.search_query(free)
            bm = self.bm25.score(self.analyzer(re.sub(r"\b(AND|OR|NOT)\b", " ", free)))
            scores = {d: bm.get(d, 0.0) + 1e-6 for d in matched}
        elif mode == "bm25":
            scores = self.bm25.score(q_terms)
        elif mode == "tfidf":
            scores = self.tfidf.score(q_terms)
        elif mode == "lm":
            scores = self.lm.score(q_terms)
        elif mode == "sdm":
            scores = self.sdm.score(q_terms)
        elif mode == "dense":
            scores = self.dense.score_text(text)
        elif mode in ("hybrid", "rrf", "adaptive"):
            L, D = self.bm25.score(q_terms), self.dense.score_text(text)
            if mode == "hybrid":
                scores = interpolate(L, D, self.cfg.hybrid_alpha)
                alpha = self.cfg.hybrid_alpha
            elif mode == "rrf":
                scores = rrf([L, D])
            else:
                alpha = self.adaptive.alpha(self.adaptive.features(q_terms, L, D))
                scores = self.adaptive.fuse(L, D, alpha)
        elif mode == "smart":
            scores, parts = self.bridge.score(q_terms, text, return_parts=True)
            orig = set(q_terms)
            expansion = [(self.surface.get(t, t), round(float(w), 3)) for t, w in sorted(parts["expansion"].items(), key=lambda x: -x[1])
                         if t not in orig and self.index.idf(t) >= 1.0 and not t.isdigit() and len(t) > 2][:8]
            alpha = self.cfg.bridge.alpha
            if context and context.strip().lower() != free.strip().lower():
                if self._context_related(context, scores):     # only a related earlier query is used as context
                    context_used = context
            scores, breakdown, reasons = self._smart(scores, q_terms, text, personal, context_used)
        else:  # bridge
            scores, parts = self.bridge.score(q_terms, text, return_parts=True)
            orig = set(q_terms)
            expansion = [(self.surface.get(t, t), round(float(w), 3)) for t, w in sorted(parts["expansion"].items(), key=lambda x: -x[1])
                         if t not in orig and self.index.idf(t) >= 1.0 and not t.isdigit() and len(t) > 2][:8]
            alpha = self.cfg.bridge.alpha

        # dense scores cover every document: keep only reasonably similar ones as "matches"
        if mode in ("dense",) and scores:
            scores = {d: s for d, s in scores.items() if s > 0.05}
        for ph in phrases:   # phrase boost
            terms = self.analyzer(ph)
            if len(terms) > 1 and scores:
                top = max(scores.values())
                for d in self.index.phrase_match(terms):
                    if d in scores:
                        scores[d] += 0.2 * abs(top)
        if pagerank_weight and scores:
            mx = max(abs(v) for v in scores.values()) or 1
            scores = {d: s / mx + pagerank_weight * self.pagerank[d] for d, s in scores.items()}
        scores = {d: s for d, s in scores.items() if d not in self.index.deleted and d < len(self.docs)}
        unfiltered = top_k(scores, 300)
        if filters:
            scores = {d: s for d, s in scores.items() if self._passes(d, filters)}

        facets = self._facets([d for d, _ in unfiltered])
        need = offset + k
        cand = top_k(scores, max(need * 3, 50))
        if diversify:
            ranked = mmr(cand, self.dense.emb, mmr_lambda, need)
        elif fair_group:
            ranked = fair_rerank(cand, lambda d: self._field(d, fair_group) or "unknown", need)
        else:
            ranked = cand
        collapsed: Dict[int, List[int]] = {}
        if dedupe and getattr(self, "dup_of", None):
            kept, seen = [], {}
            for d, sc in ranked:
                rep = self.dup_of.get(d, d)
                if rep in seen:
                    collapsed.setdefault(seen[rep], []).append(d)
                    continue
                seen[rep] = d
                kept.append((d, sc))
            ranked = kept
        ranked = ranked[offset:need]

        # evidence shown to users: share of query words present vs. semantic closeness
        qset = set(q_terms)
        qvec = self.dense.query_vector(text) if ranked and q_terms else None
        sims = {d: float(self.dense.emb[d] @ qvec) for d, _ in ranked} if qvec is not None else {}
        top_sim = max([v for v in sims.values() if v > 0], default=1.0)
        hits = []
        for r, (d, s) in enumerate(ranked, offset + 1):
            h = self._hit(r, d, s, q_terms, explain)
            if qset:
                matched = len(qset & self.index.doc_tf[d].keys()) if d < len(self.index.doc_tf) else 0
                cov = matched / len(qset)
                sem = max(0.0, sims.get(d, 0.0)) / top_sim
                tot = cov + sem
                h.signal = {"lexical": round(cov / tot, 3) if tot else 0.0, "semantic": round(sem / tot, 3) if tot else 0.0,
                            "matched": matched, "terms": len(qset)}
            if d in breakdown:
                h.breakdown = breakdown[d]
            h.personal = reasons.get(d, [])
            h.duplicates = [{"id": self.docs[x].doc_id, "title": self.docs[x].display_title} for x in collapsed.get(d, [])]
            if len(qset) > 1 and d < len(self.index.doc_tf):
                h.missing = [self.surface.get(t, t) for t in dict.fromkeys(q_terms) if t not in self.index.doc_tf[d]]
            hits.append(h)
        typed = {}
        for w in tokenize(text):                      # show the user's own words, not stems
            t = self.analyzer.analyze_term(w)
            if t:
                typed.setdefault(t, w)
        surf = {self.surface.get(t, t): w for t, w in typed.items()}
        for h in hits:
            h.missing = [surf.get(m, m) for m in h.missing]
        coverage = self._coverage(q_terms, typed) if q_terms and mode != "boolean" else {}
        if coverage and len(coverage["terms"]) > 1 and offset == 0:
            coverage["top_partial"] = bool(hits) and all(h.missing for h in hits[:3])
        related = [(n, round(float(w), 3)) for n, w in self.kg.expansion_terms(text)] if self.kg and q_terms else []
        n_match = len(scores) if mode != "dense" else min(len(scores), 1000)
        if coverage and not filters:
            n_match = coverage["any"]          # documents that contain at least one query word
        return SearchResponse(query, mode, hits, n_match, round((time.time() - t0) * 1000, 1),
                              corrected, expansion, related, alpha, facets, offset, filters, intent, context_used,
                              sum(1 for h in hits if abs(h.breakdown.get("personal", 0)) >= 0.03),
                              sum(len(v) for v in collapsed.values()), coverage, notice)

    def _coverage(self, q_terms: Sequence[str], typed: Optional[Dict[str, str]] = None) -> Dict[str, object]:
        """Document frequency of each query word, and how many documents contain any / all of them.
        Used to say honestly when the collection has nothing that matches the whole query."""
        terms = list(dict.fromkeys(q_terms))
        sets = [set(self.index.get_postings(t)) - self.index.deleted for t in terms]
        any_ = set().union(*sets) if sets else set()
        all_ = set.intersection(*sets) if sets else set()
        typed = typed or {}
        return {"terms": [typed.get(t) or self.surface.get(t, t) for t in terms], "df": [len(x) for x in sets],
                "any": len(any_), "all": len(all_), "weak": bool(terms) and (len(all_) == 0 or len(any_) == 0)}

    # ------------------------------------------------------------------ smart ranking
    W_PAGERANK, W_HITS, W_CONTEXT = 0.05, 0.05, 0.5
    # Link authority is only trusted when the graph covers enough of the collection: with a handful of
    # citations (e.g. 40 links among 2,243 papers) PageRank and HITS just reward the few linked documents.
    MIN_LINK_COVERAGE = 0.2

    @property
    def links_usable(self) -> bool:
        return bool(self.n_links) and getattr(self, "link_coverage", 1.0) >= self.MIN_LINK_COVERAGE

    def _smart(self, rel_scores: Dict[int, float], q_terms: Sequence[str], text: str,
               personal: Optional[PersonalContext], context: Optional[str], depth: int = 200):
        """Relevance first: min-max normalised Bridge-PRF score over the top `depth` candidates, plus small
        bounded additions for link authority, session context and the user's search memory."""
        cand = top_k(rel_scores, depth)
        if not cand:
            return {}, {}, {}
        vals = np.array([s for _, s in cand])
        lo, hi = float(vals.min()), float(vals.max())
        rel = {d: (s - lo) / (hi - lo) if hi > lo else 1.0 for d, s in cand}
        ids = [d for d, _ in cand]
        bd: Dict[int, Dict[str, float]] = {d: {"relevance": round(r, 4)} for d, r in rel.items()}
        final = dict(rel)
        if self.links_usable:
            auth, _, _ = self.hits_scores(ids)
            for d in ids:
                pr, au = self.W_PAGERANK * float(self.pagerank[d]), self.W_HITS * auth.get(d, 0.0)
                final[d] += pr + au
                bd[d]["pagerank"], bd[d]["hits"] = round(pr, 4), round(au, 4)
        if context:
            # session query expansion: re-score the candidates against the current query and the earlier one
            # together, and mix that in (an additive bonus cannot lift a relevant document from rank 150)
            v = self.dense.query_vector(text) + self.dense.query_vector(context)
            v = v / (np.linalg.norm(v) or 1.0)
            sub = self.dense.emb[ids] @ v
            m0, m1 = float(sub.min()), float(sub.max())
            for d, x in zip(ids, sub):
                joint = (float(x) - m0) / (m1 - m0) if m1 > m0 else 0.0
                c = self.W_CONTEXT * (joint - rel[d])          # final = (1 - W) * relevance + W * joint
                final[d] += c
                bd[d]["context"] = round(c, 4)
        reasons: Dict[int, List[str]] = {}
        if personal is not None and not personal.profile.empty:
            ps = personal.score(ids, q_terms, [x.doc_id for x in self.docs])
            for d, (p, _comp, why) in ps.items():
                g = personal_rerank.gate(rel[d]) if p > 0 else 1.0
                delta = personal.beta * g * p
                final[d] += delta
                bd[d]["personal"] = round(delta, 4)
                if why and abs(delta) >= 0.03:
                    reasons[d] = why
        for d in ids:
            bd[d]["total"] = round(final[d], 4)
        return final, bd, reasons

    def _hit(self, rank: int, d: int, s: float, q_terms: Sequence[str], explain: bool) -> Hit:
        doc = self.docs[d]
        snip = redact(snippet(doc.text or doc.title, q_terms, self.analyzer))
        cs = self.cred[d]
        expl = [(self.surface.get(t, t), tf, round(idf, 3), round(c, 3)) for t, tf, idf, c in self.bm25.explain(q_terms, d)] if explain else []
        h = Hit(rank, doc.doc_id, doc.display_title, round(float(s), 4), snip, highlight(snip, q_terms),
                round(cs.score, 2), [cs.flag] if cs.flag else [], expl, doc.meta, doc.tags[:6],
                self.doc_topic[d], cs.reasons, self.index.doc_len[d])
        h.category = self._field(d, "category")
        return h

    def _facets(self, docs: Sequence[int]) -> Dict[str, List[Tuple[str, int]]]:
        out: Dict[str, List[Tuple[str, int]]] = {}
        for f in FACET_FIELDS:
            c = Counter(self._field(d, f) for d in docs if self._field(d, f))
            if len(c) > 1 or f == "topic":
                out[f] = c.most_common(10)
        tags: Counter = Counter()
        for d in docs[:100]:
            tags.update(self.docs[d].tags)
        if tags:
            out["tag"] = [(t, n) for t, n in tags.most_common(12) if n > 1]
        return out

    # ------------------------------------------------------------------ discovery features
    def autocomplete(self, prefix: str, k: int = 8) -> List[str]:
        """Phrase completion from keyphrases, mined collocations and the vocabulary."""
        p = " ".join(tokenize(prefix))
        if len(p) < 2:
            return []
        head, _, last = p.rpartition(" ")
        out: List[Tuple[int, str]] = []
        for phrase, f in self.phrases.items():
            if phrase.startswith(p):
                out.append((f * 3, phrase))
            elif head and phrase.startswith(last) and len(last) >= 2:
                out.append((f, f"{head} {phrase}"))
        if len(out) < k:
            for w, f in self.kgram.freq.most_common():
                if w.startswith(last) and w != last and w not in STOPWORDS and len(w) > 2:
                    out.append((f // 4, f"{head} {w}".strip()))
                if len(out) >= 4 * k:
                    break
        seen, res = set(), []
        for _, s in sorted(out, key=lambda x: -x[0]):
            if s not in seen and s != p:
                seen.add(s); res.append(s)
            if len(res) == k:
                break
        return res

    def document(self, doc_id: str, query: str = "", max_chars: int = 30000) -> Dict:
        d = self.index.doc_index[doc_id]
        doc = self.docs[d]
        q_terms = self.analyzer(query) if query else []
        body = redact(doc.text[:max_chars])
        return {"doc_id": doc.doc_id, "title": doc.display_title, "meta": doc.meta, "tags": doc.tags,
                "topic": self.doc_topic[d], "html": highlight(body, q_terms), "truncated": len(doc.text) > max_chars,
                "words": self.index.doc_len[d], "pagerank": round(float(self.pagerank[d]), 3),
                "credibility": round(self.cred[d].score, 2), "credibility_reasons": self.cred[d].reasons,
                "entities": sorted(self.kg.label(e) for e in self.kg.doc_entities[d])[:30] if self.kg and d < len(self.kg.doc_entities) else [],
                "cites": [self.docs[int(i)].doc_id for i in self.out_links(d)][:40],
                "cited_by": [self.docs[int(i)].doc_id for i in self.in_links(d)][:40],
                "link_kind": self.graph_kind, "category": self._field(d, "category"),
                "category_predicted": bool(getattr(self, "category_predicted", [False] * (d + 1))[d]),
                "authority": {v: float(x["scores"][d]) for v, x in getattr(self, "pr_versions", {}).items()},
                "duplicates": [self.docs[i].doc_id for i, r in getattr(self, "dup_of", {}).items() if r == d or (i == d and False)]
                + ([self.docs[self.dup_of[d]].doc_id] if d in getattr(self, "dup_of", {}) else [])}

    def suggest(self, prefix: str, history=(), popular=None, k: int = 6) -> Dict:
        return self.suggester.suggest(prefix, history, popular, k)

    # ------------------------------------------------------------------ reports for the Insights page
    def link_report(self, top: int = 10) -> Dict:
        n = len(self.docs)
        out = {"documents": n, "links": self.n_links, "kind": self.graph_kind,
               "link_coverage": round(getattr(self, "link_coverage", 0.0), 4), "used_in_ranking": self.links_usable}
        if not self.n_links:
            return out
        outdeg = np.diff(self.link_graph.indptr)
        indeg = np.diff(self.link_in.indptr)
        linked = int(((outdeg > 0) | (indeg > 0)).sum())
        out.update({"dead_ends": int((outdeg == 0).sum()), "linked_docs": linked,
                    "max_in_degree": int(indeg.max()), "versions": {}})
        for v, x in self.pr_versions.items():
            r = x["scores"]
            order = np.argsort(-r)[:top]
            mass = x["mass"]
            step = max(1, len(mass) // 60)
            out["versions"][v] = {"iterations": x["iterations"], "final_mass": round(float(mass[-1]), 4),
                                  "mass_curve": [round(float(m), 5) for m in mass[::step]], "step": step,
                                  "top": [{"id": self.docs[i].doc_id, "title": self.docs[i].display_title,
                                           "score": float(r[i]), "in_links": int(indeg[i])} for i in order]}
        a = {v: set(np.argsort(-x["scores"])[:top].tolist()) for v, x in self.pr_versions.items()}
        out["top_overlap"] = {f"{p}-{q}": len(a[p] & a[q]) / top for p, q in (("v1", "v2"), ("v2", "v3"), ("v1", "v3"))}
        return out

    def hits_report(self, query: str, k: int = 10) -> Dict:
        resp = self.search(query, mode="bridge", k=30, explain=False)
        ids = [self.index.doc_index[h.doc_id] for h in resp.hits]
        auth, hub, edges = self.hits_scores(ids)
        fmt = lambda sc: [{"id": self.docs[d].doc_id, "title": self.docs[d].display_title, "score": round(v, 4), "in_root": d in ids}
                          for d, v in sorted(sc.items(), key=lambda x: -x[1])[:k] if v > 0]
        return {"query": query, "root": len(ids), "base": len(auth), "edges": edges, "authorities": fmt(auth), "hubs": fmt(hub)}

    def topic_report(self) -> Dict:
        from scipy.cluster.hierarchy import dendrogram
        labels = [self.topic_labels[i] for i in range(len(self.topic_labels))]
        sizes = Counter(self.doc_topic)
        out = {"topics": [{"label": lab, "size": sizes.get(lab, 0)} for lab in labels], "dendrogram": None}
        if len(labels) >= 3:
            _, Z = hac(self.topic_centroids, 1, "average")
            dn = dendrogram(Z, no_plot=True, labels=labels)
            out["dendrogram"] = {"icoord": dn["icoord"], "dcoord": dn["dcoord"], "order": dn["ivl"]}
        rng = np.random.default_rng(0)
        idx = rng.choice(len(self.docs), size=min(900, len(self.docs)), replace=False)
        X = self.dense.emb[idx] - self.dense.emb[idx].mean(0)
        U, S, Vt = np.linalg.svd(X, full_matrices=False)
        P = X @ Vt[:2].T
        lab_id = {lab: i for i, lab in enumerate(labels)}
        out["points"] = [{"x": round(float(p[0]), 4), "y": round(float(p[1]), 4), "t": lab_id.get(self.doc_topic[i], 0),
                          "id": self.docs[i].doc_id, "title": self.docs[i].display_title[:80]} for p, i in zip(P, idx)]
        out["categories"] = {"report": self.categorizer.report if self.categorizer.ok else None,
                             "predicted": int(sum(self.category_predicted)),
                             "uncategorised": int(sum(1 for c in self.doc_category if not c))}
        return out

    def duplicate_report(self, k: int = 12) -> Dict:
        return {"pairs": len(self.dup_pairs), "examples": [
            {"a": {"id": self.docs[i].doc_id, "title": self.docs[i].display_title},
             "b": {"id": self.docs[j].doc_id, "title": self.docs[j].display_title}, "jaccard": jac}
            for i, j, jac in self.dup_pairs[:k]]}

    def related_documents(self, doc_id: str, k: int = 5, weights=(0.5, 0.2, 0.2, 0.1)) -> List[Tuple[str, str, float, Dict[str, float]]]:
        """"Bridge documents": fuse semantic similarity, lexical (tf-idf) similarity,
        knowledge-graph entity overlap and graph proximity — each component returned for transparency."""
        d = self.index.doc_index[doc_id]
        sem = self.dense.emb @ self.dense.emb[d]
        cand = [int(i) for i in np.argsort(-sem)[: 50] if i != d and i not in self.index.deleted]
        top_terms = [t for t, _ in self.index.doc_tf[d].most_common(40)]
        lex = self.tfidf.score(top_terms)
        lmax = max(lex.values()) if lex else 1
        nbrs = {int(x) for x in self.out_links(d)} | {int(x) for x in self.in_links(d)}
        out = []
        for c in cand:
            parts = {"semantic": float(sem[c]), "lexical": lex.get(c, 0) / lmax,
                     "entities": self.kg.entity_overlap(d, c) if self.kg and c < len(self.kg.doc_entities) else 0.0,
                     "graph": 1.0 if c in nbrs else 0.0}
            score = sum(w * v for w, v in zip(weights, parts.values()))
            out.append((self.docs[c].doc_id, self.docs[c].display_title, round(score, 4), {k_: round(v, 3) for k_, v in parts.items()}))
        return sorted(out, key=lambda x: -x[2])[:k]

    def cluster_results(self, resp: SearchResponse, n_clusters: int = 4) -> Dict[int, Dict]:
        ids = [self.index.doc_index[h.doc_id] for h in resp.hits]
        if len(ids) < max(n_clusters, 3):
            return {0: {"label": ["All results"], "docs": [h.doc_id for h in resp.hits]}}
        lab = KMeans(n_clusters, seed=0).fit(self.dense.emb[ids]).labels_
        out: Dict[int, Dict] = {}
        for h, c, i in zip(resp.hits, lab, ids):
            out.setdefault(int(c), {"docs": [], "_ids": []})
            out[int(c)]["docs"].append(h.doc_id)
            out[int(c)]["_ids"].append(i)
        # Label each cluster with what sets it apart from the OTHER results: a keyphrase scores by its share of
        # the cluster's documents minus its share of the rest, so phrases every result has (often the query
        # itself) never win, and a phrase used for one cluster is not reused, so no two clusters look the same.
        members = {c: v.pop("_ids") for c, v in out.items()}
        all_ids = [i for ids_c in members.values() for i in ids_c]

        def doc_terms(i: int) -> set:
            tags = {t.lower() for t in self.docs[i].tags}
            # no keyphrases (e.g. news): distinctive title words only, i.e. words in under 5 % of documents
            return tags or {self.surface.get(w, w) for w in self.analyzer(self.docs[i].title)
                            if len(w) > 3 and self.index.idf(w) >= math.log10(20)}

        terms = {i: doc_terms(i) for i in all_ids}
        used: set = set()
        for c in sorted(out, key=lambda c: -len(members[c])):
            ids_c, rest = members[c], [i for i in all_ids if i not in members[c]]
            inside = Counter(t for i in ids_c for t in terms[i])
            outside = Counter(t for i in rest for t in terms[i])
            if len(ids_c) == 1:     # a single result is best described by itself
                first = self.docs[ids_c[0]]
                spare = [t for t in first.tags if t.lower() not in used]
                picked = [spare[0].lower()] if spare else [first.display_title[:48]]
                used.update(picked)
                out[c]["label"] = [_title_case_phrase(self._casing(t)) if t in spare or t.islower() else t for t in picked]
                continue
            need = 2
            scored = sorted(((n / len(ids_c) - (outside[t] / len(rest) if rest else 0.0), n, t) for t, n in inside.items()
                             if n >= need and t not in used and t not in STOPWORDS), reverse=True)
            picked: List[str] = []
            for _, _, t in scored:
                if not any(t in p or p in t for p in picked):
                    picked.append(t)
                if len(picked) == 2:
                    break
            if not picked:          # fall back to the best-ranked member's own keyphrase or title
                first = self.docs[ids_c[0]]
                spare = [t for t in first.tags if t.lower() not in used]
                picked = [spare[0].lower()] if spare else [first.display_title[:40]]
            used.update(picked)
            out[c]["label"] = [_title_case_phrase(self._casing(t)) for t in picked]
        return out

    def _casing(self, phrase: str) -> str:
        """Original capitalisation of a keyphrase (e.g. "SQL", "k-means") when a document spells it that way."""
        if not hasattr(self, "_tag_case"):
            self._tag_case = {}
            for d in self.docs:
                for t in d.tags:
                    if t != t.lower():
                        self._tag_case.setdefault(t.lower(), t)
        return self._tag_case.get(phrase, phrase)

    def feedback_search(self, query: str, relevant: Sequence[str], nonrelevant: Sequence[str] = (), k: int = 10) -> List[Tuple[str, float]]:
        """Explicit relevance feedback (Rocchio) from user-marked results."""
        rel = [self.index.doc_index[r] for r in relevant if r in self.index.doc_index]
        nrel = [self.index.doc_index[r] for r in nonrelevant if r in self.index.doc_index]
        q = rocchio(self.index, self.analyzer(query), rel, nrel)
        return [(self.docs[d].doc_id, s) for d, s in top_k(self.bm25.score_weighted(q), k)]

    def feedback_hits(self, query: str, relevant: Sequence[str], nonrelevant: Sequence[str] = (), k: int = 10) -> List[Hit]:
        q_terms = self.analyzer(query)
        return [self._hit(r, self.index.doc_index[d], s, q_terms, True)
                for r, (d, s) in enumerate(self.feedback_search(query, relevant, nonrelevant, k), 1)]

    def compare(self, query: str, modes: Sequence[str], k: int = 10) -> Dict:
        runs = {m: self.search(query, mode=m, k=k, explain=False) for m in modes}
        ids = {m: [h.doc_id for h in r.hits] for m, r in runs.items()}
        a, b = list(ids.values())[:2] if len(ids) >= 2 else (list(ids.values())[0], [])
        overlap = len(set(a) & set(b)) / max(len(set(a) | set(b)), 1)
        from .retrieval.qpp import QPP as _Q
        return {"runs": runs, "jaccard": round(overlap, 3), "rbo": round(_Q.rbo(a, b), 3) if b else None}

    def kg_view(self, query: str = "", max_nodes: int = 40, extra_seeds: Sequence[str] = (), strict: bool = False) -> Dict:
        """Concept subgraph around the query's entities (plus optional extra seeds such as the
        keyphrases of the top results). strict=True returns nothing rather than global hubs."""
        if not self.kg:
            return {"nodes": [], "edges": []}
        seeds = set(self.kg.query_entities(query)) if query else set()
        seeds |= {t.lower() for t in extra_seeds if t.lower() in self.kg.edges}
        if not seeds and (strict or query):
            return {"nodes": [], "edges": []} if strict else self.kg.subgraph(None, max_nodes)
        return self.kg.subgraph(seeds or None, max_nodes)

    # ------------------------------------------------------------------ incremental updates
    def add_document(self, doc: Document) -> None:
        """Dynamic indexing: lexical index updated immediately; dense side re-encodes the doc."""
        self.docs.append(doc)
        self.index.add_document(doc.doc_id, doc.full_text)
        vec = self.dense.encoder.encode([doc.full_text]).astype(np.float32)
        self.dense.emb = np.vstack([self.dense.emb, vec])
        self.pagerank = np.append(self.pagerank, 0.0)
        self.cred.append(credibility(doc.text, doc.meta.get("source", "")))
        if hasattr(self, "doc_category"):
            pred = self.categorizer.predict(doc.full_text[:3000]) if self.categorizer.ok else None
            self.doc_category.append(pred[0] if pred else "")
            self.category_predicted.append(bool(pred))
        self.doc_topic.append(self.doc_topic[int(np.argmax(self.dense.emb[:-1] @ vec[0]))] if self.doc_topic else "All documents")
        if self.kg:
            self.kg.doc_entities.append(self.kg.query_entities(doc.full_text))
        self._cache.clear()

    # ------------------------------------------------------------------ persistence
    def save(self, path: str | Path) -> None:
        cache, self._cache = self._cache, OrderedDict()
        try:
            with open(path, "wb") as f:
                pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
        finally:
            self._cache = cache

    @staticmethod
    def load(path: str | Path) -> "SearchEngine":
        with open(path, "rb") as f:
            return pickle.load(f)

    def stats(self) -> Dict[str, object]:
        s = self.index.stats()
        return {"documents": s.num_docs, "vocabulary": s.num_terms, "postings": s.num_postings,
                "tokens": s.num_tokens, "avg_doc_len": round(s.avg_doc_len, 1),
                "dense_encoder": self.dense.name.replace("Dense (", "").rstrip(")"), "link_graph": self.graph_kind,
                "kg_entities": len(self.kg.entity_docs) if self.kg else 0, "topics": len(self.topic_labels),
                "links": getattr(self, "n_links", 0), "near_duplicates": len(getattr(self, "dup_of", {})),
                "build_seconds": round(self.build_seconds, 2)}
