"""Lexical ranked-retrieval models (Syllabus Module 2).

* TFIDFRetriever  - vector space model, SMART lnc.ltc weighting + cosine (IIR §6.4)
* BM25Retriever   - Okapi BM25 (Robertson & Zaragoza, 2009) with per-term explanations
* LMRetriever     - query-likelihood language model, Dirichlet or Jelinek-Mercer smoothing
                    (Ponte & Croft 1998; Zhai & Lafferty 2004)

All retrievers share: score(query_terms) -> {doc_int: score}; search(...) -> ranked list.
Term-at-a-time accumulation over postings, so only docs sharing a term are touched.
"""
from __future__ import annotations

import heapq
import math
from collections import Counter
from typing import Dict, List, Sequence, Tuple  # noqa: F401

from ..index.inverted_index import InvertedIndex

Ranked = List[Tuple[int, float]]


def top_k(scores: Dict[int, float], k: int) -> Ranked:
    return heapq.nlargest(k, scores.items(), key=lambda kv: (kv[1], -kv[0]))


class Retriever:
    name = "base"

    def __init__(self, index: InvertedIndex):
        self.index = index

    def score(self, q_terms: Sequence[str]) -> Dict[int, float]:  # pragma: no cover
        raise NotImplementedError

    def search(self, q_terms: Sequence[str], k: int = 10) -> Ranked:
        return top_k(self.score(q_terms), k)


class TFIDFRetriever(Retriever):
    """lnc.ltc: doc = (1+log tf), no idf, cosine; query = (1+log tf)*idf, cosine."""
    name = "TF-IDF (VSM)"

    def __init__(self, index: InvertedIndex):
        super().__init__(index)
        self.doc_norm = [math.sqrt(sum((1 + math.log10(tf)) ** 2 for tf in c.values())) or 1.0
                         for c in index.doc_tf]

    def score(self, q_terms):
        qtf = Counter(q_terms)
        qw = {t: (1 + math.log10(tf)) * self.index.idf(t) for t, tf in qtf.items()}
        qn = math.sqrt(sum(w * w for w in qw.values())) or 1.0
        acc: Dict[int, float] = {}
        for t, w in qw.items():
            if w == 0:
                continue
            for d, pos in self.index.get_postings(t).items():
                acc[d] = acc.get(d, 0.0) + w * (1 + math.log10(len(pos)))
        return {d: s / (self.doc_norm[d] * qn) for d, s in acc.items()}


class BM25Retriever(Retriever):
    name = "BM25"

    def __init__(self, index: InvertedIndex, k1: float = 1.2, b: float = 0.75):
        super().__init__(index)
        self.k1, self.b = k1, b
        self._avgdl = index.avgdl

    def idf(self, t: str) -> float:
        n, df = self.index.N, self.index.df(t)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))  # Lucene variant, always > 0

    def _term_score(self, tf: int, dl: int, idf: float) -> float:
        k1, b = self.k1, self.b
        return idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / self._avgdl))

    def score(self, q_terms):
        acc: Dict[int, float] = {}
        for t, qtf in Counter(q_terms).items():
            idf = self.idf(t)
            for d, pos in self.index.get_postings(t).items():
                acc[d] = acc.get(d, 0.0) + qtf * self._term_score(len(pos), self.index.doc_len[d], idf)
        return acc

    def score_weighted(self, q_weights: Dict[str, float]) -> Dict[int, float]:
        """Weighted query (used after RM3 / Rocchio expansion)."""
        acc: Dict[int, float] = {}
        for t, w in q_weights.items():
            idf = self.idf(t)
            for d, pos in self.index.get_postings(t).items():
                acc[d] = acc.get(d, 0.0) + w * self._term_score(len(pos), self.index.doc_len[d], idf)
        return acc

    def explain(self, q_terms: Sequence[str], doc: int) -> List[Tuple[str, int, float, float]]:
        """Per-term (term, tf, idf, contribution): makes every ranking auditable."""
        rows = []
        for t in dict.fromkeys(q_terms):
            tf = len(self.index.get_postings(t).get(doc, []))
            idf = self.idf(t)
            rows.append((t, tf, idf, self._term_score(tf, self.index.doc_len[doc], idf) if tf else 0.0))
        return sorted(rows, key=lambda r: -r[3])


class LMRetriever(Retriever):
    """Query likelihood. Scores are log P(q|d) shifted so only matching docs are returned
    (rank-equivalent to the full sum; see Zhai & Lafferty 2004, Eq. 3)."""
    name = "QL-LM"

    def __init__(self, index: InvertedIndex, method: str = "dirichlet", mu: float = 2000, lam: float = 0.7):
        super().__init__(index)
        self.method, self.mu, self.lam = method, mu, lam
        cf = index.collection_tf()
        self.C = sum(cf.values())
        self.p_c = {t: c / self.C for t, c in cf.items()}
        self.name = f"QL-LM ({method})"

    def score(self, q_terms):
        acc: Dict[int, float] = {}
        qtf = Counter(t for t in q_terms if t in self.p_c)
        dl = self.index.doc_len
        for t, c in qtf.items():
            pc = self.p_c[t]
            for d, pos in self.index.get_postings(t).items():
                tf = len(pos)
                if self.method == "dirichlet":
                    s = math.log(1 + tf / (self.mu * pc))
                else:  # Jelinek-Mercer
                    s = math.log(1 + (self.lam * tf / dl[d]) / ((1 - self.lam) * pc))
                acc[d] = acc.get(d, 0.0) + c * s
        if self.method == "dirichlet":
            qlen = sum(qtf.values())
            for d in acc:
                acc[d] += qlen * math.log(self.mu / (dl[d] + self.mu))
        return acc


class SDMRetriever(LMRetriever):
    """Sequential Dependence Model — the Markov-random-field model of Metzler & Croft (SIGIR 2005).

    score(Q,D) = λT Σ f_T(q_i, D) + λO Σ f_O(q_i q_{i+1}, D) + λU Σ f_U(q_i q_{i+1}, D)
    f_T: Dirichlet-smoothed unigram, f_O: exact ordered bigram (#1), f_U: unordered window (#uw8).
    Uses the positional index, so adjacency/proximity of query terms is rewarded.
    """
    name = "SDM (MRF)"

    def __init__(self, index: InvertedIndex, mu: float = 300, weights=(0.85, 0.10, 0.05), window: int = 8):
        super().__init__(index, "dirichlet", mu=mu)
        self.name = "SDM (MRF)"
        self.wT, self.wO, self.wU = weights
        self.window = window

    def _pair_counts(self, a: str, b: str):
        pa, pb = self.index.get_postings(a), self.index.get_postings(b)
        ordered, unordered = {}, {}
        for d in set(pa) & set(pb):
            sb = set(pb[d])
            o = sum((p + 1) in sb for p in pa[d])
            u = sum(any(abs(p - q) < self.window for q in pb[d]) for p in pa[d])
            if o:
                ordered[d] = o
            if u:
                unordered[d] = u
        return ordered, unordered

    def _feature(self, tf: float, dl: int, cf: float) -> float:
        p_c = (cf + 0.5) / self.C
        return math.log((tf + self.mu * p_c) / (dl + self.mu))

    def score(self, q_terms):
        q = [t for t in q_terms if t in self.p_c]
        dl = self.index.doc_len
        uni = LMRetriever.score(self, q)   # rank-equivalent unigram part (matching docs only)
        cand = set(uni)
        out = {d: self.wT * s for d, s in uni.items()}
        for a, b in zip(q, q[1:]):
            o, u = self._pair_counts(a, b)
            cf_o, cf_u = sum(o.values()), sum(u.values())
            for d in cand:
                out[d] += self.wO * self._feature(o.get(d, 0), dl[d], cf_o) + self.wU * self._feature(u.get(d, 0), dl[d], cf_u)
        return out


class BM25FRetriever:
    """BM25F (Robertson, Zaragoza & Taylor, CIKM 2004; Zaragoza et al., TREC 2004): field-weighted BM25.

    Per term:  tf~ = sum_f  w_f * tf_f / (1 - b_f + b_f * len_f / avglen_f)
               score += idf(t) * tf~ / (k1 + tf~)
    Field-level normalisation lets a match in a short field (title, skills) count for more than the
    same match buried in a long field (bio, portfolio), and saturation is applied once, after
    combining fields, which is what distinguishes BM25F from a weighted sum of per-field BM25s.
    """
    name = "BM25F"

    def __init__(self, fields: Dict[str, InvertedIndex], weights: Dict[str, float], b: Dict[str, float] | None = None,
                 k1: float = 1.2, idf_index: InvertedIndex | None = None):
        self.fields, self.weights = fields, weights
        self.b = b or {f: 0.75 for f in fields}
        self.k1 = k1
        self.avg = {f: ix.avgdl or 1.0 for f, ix in fields.items()}
        self.idx = idf_index or next(iter(fields.values()))

    def idf(self, t: str) -> float:
        n, df = self.idx.N, self.idx.df(t)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def term_tf(self, t: str) -> Dict[int, float]:
        acc: Dict[int, float] = {}
        for f, ix in self.fields.items():
            w, b, avg = self.weights[f], self.b[f], self.avg[f]
            for d, pos in ix.get_postings(t).items():
                acc[d] = acc.get(d, 0.0) + w * len(pos) / (1 - b + b * ix.doc_len[d] / avg)
        return acc

    def score_weighted(self, q_weights: Dict[str, float]) -> Dict[int, float]:
        out: Dict[int, float] = {}
        for t, qw in q_weights.items():
            idf = self.idf(t)
            for d, tf in self.term_tf(t).items():
                out[d] = out.get(d, 0.0) + qw * idf * tf / (self.k1 + tf)
        return out

    def score(self, q_terms: Sequence[str]) -> Dict[int, float]:
        return self.score_weighted(dict(Counter(q_terms)))

    def explain(self, q_terms: Sequence[str], d: int) -> List[Tuple[str, Dict[str, int], float]]:
        rows = []
        for t in dict.fromkeys(q_terms):
            per_field = {f: len(ix.get_postings(t).get(d, [])) for f, ix in self.fields.items()}
            tf = sum(self.weights[f] * per_field[f] / (1 - self.b[f] + self.b[f] * self.fields[f].doc_len[d] / self.avg[f])
                     for f in self.fields if per_field[f])
            rows.append((t, per_field, round(self.idf(t) * tf / (self.k1 + tf), 4) if tf else 0.0))
        return sorted(rows, key=lambda r: -r[2])
