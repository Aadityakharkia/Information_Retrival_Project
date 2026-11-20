"""Bridge-PRF: cross-retriever pseudo-relevance feedback (project novelty #1).

Idea
----
Classic PRF expands a query using the top-k documents of the *same* retriever, so it
inherits that retriever's blind spots (vocabulary mismatch for BM25, topic drift for
dense models). Bridge-PRF takes the top-k documents of the *hybrid* (lexical ⊕ semantic)
ranking as a shared feedback set and feeds it back into BOTH representations:

    1. first pass   : L0 = BM25(q),  D0 = Dense(q),  H0 = fuse(L0, D0; a)
    2. feedback set : F  = top-k(H0)
    3. lexical PRF  : L1 = BM25(RM3(q, F))                     (term space)
    4. dense PRF    : D1 = cos(E, normalize(q_vec + b * mean(E[F])))   (vector-Rocchio)
    5. final        : fuse(L1, D1; a)

Each retriever thereby "learns" from documents the other one found — the bridge that
gives SearchBridge its name. Related work: RM3 (Abdul-Jaleel et al., 2004); vector PRF
for dense retrievers (Li et al., "Pseudo Relevance Feedback with Deep Language Models and
Dense Retrievers: Successes and Pitfalls", TOIS 2023); hybrid fusion (Cormack et al., 2009).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .fusion import interpolate
from .lexical import BM25Retriever, top_k
from .semantic import DenseRetriever
from ..query.feedback import rm3


@dataclass
class BridgePRFConfig:
    fb_docs: int = 5           # k
    alpha: float = 0.3         # lexical weight in both fusions
    dense_beta: float = 0.8    # weight of feedback centroid in vector-Rocchio
    fb_terms: int = 10         # RM3 expansion terms
    orig_weight: float = 0.6   # RM3 original-query weight


class BridgePRF:
    name = "Bridge-PRF (ours)"

    def __init__(self, bm25: BM25Retriever, dense: DenseRetriever, cfg: BridgePRFConfig | None = None):
        self.bm25, self.dense, self.cfg = bm25, dense, cfg or BridgePRFConfig()

    def first_pass(self, q_terms: Sequence[str], q_text: str):
        L0 = self.bm25.score(q_terms)
        D0 = self.dense.score_text(q_text)
        return L0, D0, interpolate(L0, D0, self.cfg.alpha)

    def score(self, q_terms: Sequence[str], q_text: str, return_parts: bool = False):
        c = self.cfg
        L0, D0, H0 = self.first_pass(q_terms, q_text)
        query_vector = self.dense.query_vector(q_text)
        if not L0 and not np.any(query_vector):
            if return_parts:
                return {}, {"L0": L0, "D0": D0, "H0": {}, "L1": {}, "D1": {}, "feedback": [], "expansion": {}}
            return {}
        fb = top_k(H0, c.fb_docs)
        if not q_terms:
            L1 = {}
        else:
            weights = rm3(self.bm25.index, q_terms, [(d, L0.get(d, 0.0)) for d, _ in fb], c.fb_terms, c.orig_weight)
            L1 = self.bm25.score_weighted(weights)
        E = self.dense.emb
        qv = query_vector + c.dense_beta * E[[d for d, _ in fb]].mean(0)
        qv /= np.linalg.norm(qv) or 1.0
        D1 = {i: float(s) for i, s in enumerate(E @ qv)}
        final = interpolate(L1, D1, c.alpha) if L1 else D1
        if return_parts:
            return final, {"L0": L0, "D0": D0, "H0": H0, "L1": L1, "D1": D1, "feedback": fb,
                           "expansion": weights if q_terms else {}}
        return final
