"""Query Performance Prediction (QPP) features.

Pre-retrieval (computed from index statistics only):
  * avgIDF / maxIDF                     (Cronen-Townsend et al.; He & Ounis 2004)
  * SCQ  - collection-query similarity  (Zhao, Scholer & Tsegay, ECIR 2008)
  * SCS  - simplified clarity score     (He & Ounis, SPIRE 2004)
  * OOV ratio, query length
Post-retrieval (from a ranked list):
  * NQC  - normalised query commitment  (Shtok, Kurland et al., TOIS 2012)
  * WIG  - weighted information gain    (Zhou & Croft, SIGIR 2007)
  * RBO  - rank-biased overlap between two runs (Webber, Moffat & Zobel, TOIS 2010)
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Sequence

import numpy as np

from ..index.inverted_index import InvertedIndex


class QPP:
    def __init__(self, index: InvertedIndex):
        self.ix = index
        cf = index.collection_tf()
        self.cf, self.C = cf, sum(cf.values())

    # ---------------------------------------------------------------- pre-retrieval
    def pre(self, q_terms: Sequence[str], raw_tokens: Sequence[str] = ()) -> Dict[str, float]:
        ix, N = self.ix, self.ix.N
        terms = list(q_terms)
        known = [t for t in terms if ix.df(t) > 0]
        idfs = [math.log(N / ix.df(t)) for t in known] or [0.0]
        scq = [(1 + math.log(self.cf[t])) * math.log(1 + N / ix.df(t)) for t in known] or [0.0]
        qtf = Counter(terms)
        scs = sum((c / len(terms)) * math.log2((c / len(terms)) / (self.cf[t] / self.C))
                  for t, c in qtf.items() if self.cf.get(t)) if terms else 0.0
        return {
            "avg_idf": float(np.mean(idfs)), "max_idf": float(np.max(idfs)),
            "avg_scq": float(np.mean(scq)), "scs": scs,
            "qlen": float(len(terms)),
            "oov": 1 - len(known) / max(len(terms), 1),
        }

    # ---------------------------------------------------------------- post-retrieval
    @staticmethod
    def nqc(scores: Sequence[float], corpus_score: float = 1.0, k: int = 100) -> float:
        s = np.array(sorted(scores, reverse=True)[:k], dtype=float)
        if len(s) < 2:
            return 0.0
        return float(s.std() / (abs(corpus_score) + 1e-9))

    @staticmethod
    def wig(scores: Sequence[float], corpus_score: float, qlen: int, k: int = 5) -> float:
        s = np.array(sorted(scores, reverse=True)[:k], dtype=float)
        return float((s - corpus_score).mean() / math.sqrt(max(qlen, 1))) if len(s) else 0.0

    @staticmethod
    def rbo(a: List[int], b: List[int], p: float = 0.9) -> float:
        """Rank-biased overlap (extrapolated) between two rankings."""
        depth = min(len(a), len(b))
        if depth == 0:
            return 0.0
        sa, sb, overlap, acc = set(), set(), 0, 0.0
        for d in range(1, depth + 1):
            x, y = a[d - 1], b[d - 1]
            if x == y:
                overlap += 1
            else:
                overlap += (x in sb) + (y in sa)
            sa.add(x); sb.add(y)
            acc += (overlap / d) * p ** d
        return float((1 - p) / p * acc + (overlap / depth) * p ** depth)
