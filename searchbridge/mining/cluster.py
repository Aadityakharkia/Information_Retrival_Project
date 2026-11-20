"""Clustering (Syllabus Module 6; IIR Ch. 16-17).

* KMeans (k-means++ seeding, spherical / cosine variant for text)
* HAC   single / complete / average / centroid linkage (via SciPy) + dendrogram cut
* Cluster labelling by distinctive centroid terms (IIR §17.7)
* Term clustering using documents (terms represented by their document vectors)
* External quality: purity, NMI, Rand index (IIR §16.3)

In SearchBridge, result clustering groups the top-N hits into labelled topics
(Scatter/Gather-style navigation; Cutting et al., SIGIR 1992).
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Sequence, Tuple

import numpy as np


def _rows_normalize(X: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(X, axis=1, keepdims=True)
    n[n == 0] = 1
    return X / n


class KMeans:
    def __init__(self, k: int, max_iter: int = 100, n_init: int = 5, seed: int = 0, spherical: bool = True):
        self.k, self.max_iter, self.n_init, self.seed, self.spherical = k, max_iter, n_init, seed, spherical

    def _init(self, X, rng):
        C = [X[rng.integers(len(X))]]
        for _ in range(1, self.k):
            d2 = np.min(((X[:, None, :] - np.array(C)[None]) ** 2).sum(-1), axis=1)
            p = d2 / d2.sum() if d2.sum() > 0 else None
            C.append(X[rng.choice(len(X), p=p)])
        return np.array(C)

    def fit(self, X: np.ndarray) -> "KMeans":
        X = _rows_normalize(X) if self.spherical else X
        rng = np.random.default_rng(self.seed)
        best = (np.inf, None, None)
        for _ in range(self.n_init):
            C = self._init(X, rng)
            for _ in range(self.max_iter):
                d = ((X[:, None, :] - C[None]) ** 2).sum(-1)
                lab = d.argmin(1)
                newC = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(self.k)])
                if self.spherical:
                    newC = _rows_normalize(newC)
                if np.allclose(newC, C):
                    break
                C = newC
            rss = float(((X - C[lab]) ** 2).sum())
            if rss < best[0]:
                best = (rss, C, lab)
        self.rss_, self.centroids_, self.labels_ = best
        return self


def hac(X: np.ndarray, k: int, linkage: str = "average") -> Tuple[np.ndarray, np.ndarray]:
    """Returns (labels, scipy linkage matrix). Cosine distance for text."""
    from scipy.cluster.hierarchy import fcluster, linkage as _link
    from scipy.spatial.distance import squareform
    Xn = _rows_normalize(np.asarray(X, dtype=float))
    if linkage in ("centroid", "ward"):
        Z = _link(Xn, method=linkage, metric="euclidean")
    else:
        D = np.clip(1 - Xn @ Xn.T, 0, 2)
        np.fill_diagonal(D, 0)
        Z = _link(squareform((D + D.T) / 2, checks=False), method=linkage)
    return fcluster(Z, k, criterion="maxclust") - 1, Z


def label_clusters(X: np.ndarray, labels: np.ndarray, vocab: Sequence[str], top: int = 4) -> Dict[int, List[str]]:
    """Terms with highest (cluster centroid weight - global centroid weight)."""
    g = X.mean(0)
    out = {}
    for c in np.unique(labels):
        diff = X[labels == c].mean(0) - g
        out[int(c)] = [vocab[i] for i in np.argsort(-diff)[:top]]
    return out


def term_clusters(term_doc: np.ndarray, terms: Sequence[str], k: int) -> Dict[int, List[str]]:
    lab = KMeans(k).fit(term_doc).labels_
    out: Dict[int, List[str]] = {}
    for t, c in zip(terms, lab):
        out.setdefault(int(c), []).append(t)
    return out


# ------------------------------------------------------------------ external evaluation
def purity(labels: Sequence[int], gold: Sequence[str]) -> float:
    by: Dict[int, Counter] = {}
    for l, g in zip(labels, gold):
        by.setdefault(l, Counter())[g] += 1
    return sum(c.most_common(1)[0][1] for c in by.values()) / len(gold)


def nmi(labels: Sequence[int], gold: Sequence[str]) -> float:
    n = len(gold)
    cw, cc, joint = Counter(labels), Counter(gold), Counter(zip(labels, gold))
    I = sum(v / n * math.log((v * n) / (cw[w] * cc[c])) for (w, c), v in joint.items())
    H = lambda cnt: -sum(v / n * math.log(v / n) for v in cnt.values())
    d = (H(cw) + H(cc)) / 2
    return I / d if d else 0.0


def rand_index(labels: Sequence[int], gold: Sequence[str]) -> float:
    n = len(gold)
    agree = sum((labels[i] == labels[j]) == (gold[i] == gold[j]) for i in range(n) for j in range(i + 1, n))
    return agree / (n * (n - 1) / 2)
