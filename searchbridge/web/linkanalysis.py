"""Link analysis (Syllabus Module 7; IIR Ch. 21).

* PageRank via power iteration with teleportation & dangling-node handling (Brin & Page, 1998)
* Personalised / topic-sensitive PageRank (Haveliwala, WWW 2002)
* HITS hubs & authorities (Kleinberg, JACM 1999)
* similarity_graph(): builds a kNN graph when a corpus has no hyperlinks/citations,
  so graph centrality can still act as a query-independent prior (cf. LexRank, Erkan & Radev 2004).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import sparse


def adjacency(n: int, edges: Sequence[Tuple[int, int]], weights: Optional[Sequence[float]] = None) -> sparse.csr_matrix:
    if not edges:
        return sparse.csr_matrix((n, n))
    r, c = zip(*edges)
    w = weights if weights is not None else np.ones(len(edges))
    return sparse.csr_matrix((w, (r, c)), shape=(n, n))


def pagerank(A: sparse.csr_matrix, damping: float = 0.85, tol: float = 1e-10, max_iter: int = 200,
             personalization: Optional[np.ndarray] = None) -> np.ndarray:
    n = A.shape[0]
    out_deg = np.asarray(A.sum(1)).ravel()
    dangling = out_deg == 0
    inv = np.where(dangling, 0, 1 / np.where(dangling, 1, out_deg))
    P = sparse.diags(inv) @ A                       # row-stochastic (except dangling rows)
    v = personalization / personalization.sum() if personalization is not None else np.full(n, 1 / n)
    x = np.full(n, 1 / n)
    for _ in range(max_iter):
        x_new = damping * (P.T @ x + x[dangling].sum() * v) + (1 - damping) * v
        if np.abs(x_new - x).sum() < tol:
            return x_new
        x = x_new
    return x


def hits(A: sparse.csr_matrix, max_iter: int = 100, tol: float = 1e-10) -> Tuple[np.ndarray, np.ndarray]:
    n = A.shape[0]
    h = np.ones(n)
    a = np.ones(n)
    for _ in range(max_iter):
        a_new = A.T @ h
        a_new /= np.linalg.norm(a_new) or 1
        h_new = A @ a_new
        h_new /= np.linalg.norm(h_new) or 1
        if np.abs(a_new - a).sum() + np.abs(h_new - h).sum() < tol:
            return h_new, a_new
        a, h = a_new, h_new
    return h, a


def similarity_graph(emb: np.ndarray, k: int = 10, min_sim: float = 0.2) -> sparse.csr_matrix:
    """Directed kNN graph over L2-normalised embeddings."""
    S = emb @ emb.T
    np.fill_diagonal(S, -1)
    n = len(S)
    rows, cols, vals = [], [], []
    for i in range(n):
        idx = np.argpartition(-S[i], min(k, n - 1))[:k]
        for j in idx:
            if S[i, j] >= min_sim:
                rows.append(i); cols.append(int(j)); vals.append(float(S[i, j]))
    return sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))


def links_to_graph(doc_links: List[List[str]], id_lookup: Dict[str, int]) -> sparse.csr_matrix:
    edges = [(i, id_lookup[t]) for i, ls in enumerate(doc_links) for t in ls if t in id_lookup and id_lookup[t] != i]
    return adjacency(len(doc_links), sorted(set(edges)))


# ---------------------------------------------------------------------------------------------
# Three versions of PageRank, kept separate so their behaviour can be compared
# (formulation follows Leskovec, Rajaraman & Ullman, "Mining of Massive Datasets", ch. 5).
#
#   V1  simplified PageRank           r = M r                 (no teleport)
#       -> rank "leaks" out of dead ends (pages without out-links) and is absorbed by spider traps.
#   V2  PageRank with teleportation   r = beta M r + (1-beta)/N
#       -> random jumps rescue rank from spider traps, but dead ends still leak (total mass < 1).
#   V3  complete PageRank             dead ends redistribute uniformly (or to the personalisation set),
#       r = beta (M r + d.r v) + (1-beta) v   with an optional topic-sensitive teleport vector v.
# ---------------------------------------------------------------------------------------------
def _column_stochastic_parts(A: sparse.csr_matrix):
    out_deg = np.asarray(A.sum(1)).ravel()
    dangling = out_deg == 0
    inv = np.where(dangling, 0, 1 / np.where(dangling, 1, out_deg))
    return (sparse.diags(inv) @ A).T.tocsr(), dangling     # M (column-stochastic, transposed for M @ r)


def pagerank_v1(A: sparse.csr_matrix, tol: float = 1e-10, max_iter: int = 100):
    M, _ = _column_stochastic_parts(A)
    n = A.shape[0]
    r = np.full(n, 1 / n)
    history = [1.0]
    for it in range(1, max_iter + 1):
        r_new = M @ r
        history.append(float(r_new.sum()))
        if np.abs(r_new - r).sum() < tol:
            return r_new, it, history
        r = r_new
    return r, max_iter, history


def pagerank_v2(A: sparse.csr_matrix, beta: float = 0.85, tol: float = 1e-10, max_iter: int = 200):
    M, _ = _column_stochastic_parts(A)
    n = A.shape[0]
    r = np.full(n, 1 / n)
    history = [1.0]
    for it in range(1, max_iter + 1):
        r_new = beta * (M @ r) + (1 - beta) / n
        history.append(float(r_new.sum()))
        if np.abs(r_new - r).sum() < tol:
            return r_new, it, history
        r = r_new
    return r, max_iter, history


def pagerank_v3(A: sparse.csr_matrix, beta: float = 0.85, personalization: Optional[np.ndarray] = None,
                tol: float = 1e-10, max_iter: int = 200):
    M, dangling = _column_stochastic_parts(A)
    n = A.shape[0]
    v = personalization / personalization.sum() if personalization is not None else np.full(n, 1 / n)
    r = np.full(n, 1 / n)
    history = [1.0]
    for it in range(1, max_iter + 1):
        r_new = beta * (M @ r + r[dangling].sum() * v) + (1 - beta) * v
        r_new /= r_new.sum()
        history.append(float(r_new.sum()))
        if np.abs(r_new - r).sum() < tol:
            return r_new, it, history
        r = r_new
    return r, max_iter, history
