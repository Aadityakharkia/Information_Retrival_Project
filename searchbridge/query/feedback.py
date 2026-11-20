"""Query operations (Syllabus Module 5): relevance feedback and query expansion.

* Rocchio (1971) explicit relevance feedback in tf-idf space (IIR §9.1.1)
* RM3 pseudo-relevance feedback (Lavrenko & Croft 2001; Abdul-Jaleel et al., TREC 2004)
* Association-thesaurus expansion from term co-occurrence (IIR §9.2.3)
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from ..index.inverted_index import InvertedIndex


def _tfidf_vec(ix: InvertedIndex, tf: Counter) -> Dict[str, float]:
    v = {t: (1 + math.log10(c)) * ix.idf(t) for t, c in tf.items()}
    n = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {t: x / n for t, x in v.items()}


def rocchio(ix: InvertedIndex, q_terms: Sequence[str], relevant: Iterable[int], nonrelevant: Iterable[int] = (),
            alpha: float = 1.0, beta: float = 0.75, gamma: float = 0.15, max_terms: int = 30) -> Dict[str, float]:
    """q_m = a*q0 + b*centroid(R) - g*centroid(NR); negative weights clipped to 0."""
    q = defaultdict(float, {t: alpha * w for t, w in _tfidf_vec(ix, Counter(q_terms)).items()})
    rel, nrel = list(relevant), list(nonrelevant)
    for docs, coef in ((rel, beta), (nrel, -gamma)):
        for d in docs:
            for t, w in _tfidf_vec(ix, ix.doc_tf[d]).items():
                q[t] += coef * w / len(docs)
    top = sorted(((t, w) for t, w in q.items() if w > 0), key=lambda x: -x[1])[:max_terms]
    return dict(top)


def rm3(ix: InvertedIndex, q_terms: Sequence[str], feedback: List[Tuple[int, float]], fb_terms: int = 10,
        orig_weight: float = 0.6) -> Dict[str, float]:
    """Relevance model from top-k docs, P(w|R) ∝ Σ_d P(w|d) P(q|d), interpolated with the
    original query. `feedback` is [(doc, score)] from a first-pass run (scores ~ log-likelihoods
    or BM25; we softmax them into document weights)."""
    if not feedback:
        return {t: 1.0 for t in q_terms}
    s = np.array([sc for _, sc in feedback], dtype=float)
    w = np.exp(s - s.max())
    w /= w.sum()
    rm: Dict[str, float] = defaultdict(float)
    for (d, _), wd in zip(feedback, w):
        dl = ix.doc_len[d] or 1
        for t, c in ix.doc_tf[d].items():
            rm[t] += wd * c / dl
    top = sorted(rm.items(), key=lambda x: -x[1])[:fb_terms]
    z = sum(v for _, v in top) or 1.0
    qtf = Counter(q_terms)
    out: Dict[str, float] = defaultdict(float)
    for t, c in qtf.items():
        out[t] += orig_weight * c / len(q_terms)
    for t, v in top:
        out[t] += (1 - orig_weight) * v / z
    return dict(out)


class AssociationThesaurus:
    """Term-term similarity from normalised document co-occurrence (C = A·Aᵀ, cosine)."""

    def __init__(self, ix: InvertedIndex, min_df: int = 3, max_df_ratio: float = 0.3):
        from scipy import sparse

        vocab = [t for t, p in ix.postings.items() if min_df <= len(p) <= max_df_ratio * ix.N]
        self.vocab = vocab
        self.tid = {t: i for i, t in enumerate(vocab)}
        rows, cols, vals = [], [], []
        for t, i in self.tid.items():
            for d, pos in ix.postings[t].items():
                rows.append(i); cols.append(d); vals.append(1 + math.log(len(pos)))
        A = sparse.csr_matrix((vals, (rows, cols)), shape=(len(vocab), len(ix.doc_ids)))
        norms = np.sqrt(A.multiply(A).sum(1)).A1
        norms[norms == 0] = 1
        self.A = sparse.diags(1 / norms) @ A

    def neighbours(self, term: str, k: int = 5) -> List[Tuple[str, float]]:
        i = self.tid.get(term)
        if i is None:
            return []
        sims = (self.A @ self.A[i].T).toarray().ravel()
        sims[i] = -1
        idx = np.argsort(-sims)[:k]
        return [(self.vocab[j], float(sims[j])) for j in idx if sims[j] > 0]

    def expand(self, q_terms: Sequence[str], per_term: int = 2, weight: float = 0.3) -> Dict[str, float]:
        out: Dict[str, float] = defaultdict(float)
        for t in q_terms:
            out[t] += 1.0
            for n, s in self.neighbours(t, per_term):
                out[n] += weight * s
        return dict(out)
