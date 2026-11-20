"""IR evaluation measures (Syllabus Module 4; IIR Ch. 8; Buckley & Voorhees 2004 for BPref).

`run`   : ranked list of doc ids (best first)
`qrels` : {doc_id: graded relevance (>0 = relevant)}; unlisted docs are non-relevant.
`judged`: optional set of judged doc ids (relevant + judged non-relevant), needed by BPref.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np


def _rel(qrels: Dict[str, int]) -> Set[str]:
    return {d for d, g in qrels.items() if g > 0}


def precision_at(run: Sequence[str], qrels, k: int) -> float:
    rel = _rel(qrels)
    return sum(d in rel for d in run[:k]) / k


def recall_at(run: Sequence[str], qrels, k: int) -> float:
    rel = _rel(qrels)
    return sum(d in rel for d in run[:k]) / len(rel) if rel else 0.0


def precision_recall_f1(retrieved: Iterable[str], qrels) -> Tuple[float, float, float]:
    """Set-based measures (for Boolean retrieval)."""
    ret, rel = set(retrieved), _rel(qrels)
    tp = len(ret & rel)
    p = tp / len(ret) if ret else 0.0
    r = tp / len(rel) if rel else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def average_precision(run: Sequence[str], qrels) -> float:
    rel = _rel(qrels)
    if not rel:
        return 0.0
    hits, s = 0, 0.0
    for i, d in enumerate(run, 1):
        if d in rel:
            hits += 1
            s += hits / i
    return s / len(rel)


def reciprocal_rank(run: Sequence[str], qrels) -> float:
    rel = _rel(qrels)
    for i, d in enumerate(run, 1):
        if d in rel:
            return 1.0 / i
    return 0.0


def ndcg_at(run: Sequence[str], qrels, k: int = 10) -> float:
    """nDCG with exponential gain (2^g - 1) / log2(i+1) (Järvelin & Kekäläinen, 2002)."""
    dcg = sum((2 ** qrels.get(d, 0) - 1) / math.log2(i + 1) for i, d in enumerate(run[:k], 1))
    ideal = sorted((g for g in qrels.values() if g > 0), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    return dcg / idcg if idcg else 0.0


def r_precision(run: Sequence[str], qrels) -> float:
    R = len(_rel(qrels))
    return precision_at(run, qrels, R) if R else 0.0


def bpref(run: Sequence[str], qrels, judged: Optional[Set[str]] = None) -> float:
    """BPref: robust to incomplete judgements; only judged non-relevant docs count."""
    rel = _rel(qrels)
    R = len(rel)
    if not R:
        return 0.0
    judged = judged if judged is not None else set(qrels)
    nonrel_judged = judged - rel
    N = len(nonrel_judged)
    seen_nonrel, s = 0, 0.0
    for d in run:
        if d in rel:
            s += 1 - (min(seen_nonrel, R) / min(R, N) if N else 0.0)
        elif d in nonrel_judged:
            seen_nonrel += 1
    return s / R


def interpolated_pr_curve(run: Sequence[str], qrels, levels: int = 11) -> np.ndarray:
    """11-point interpolated precision (IIR §8.4)."""
    rel = _rel(qrels)
    pts = np.linspace(0, 1, levels)
    if not rel:
        return np.zeros(levels)
    prec, rec, hits = [], [], 0
    for i, d in enumerate(run, 1):
        hits += d in rel
        prec.append(hits / i)
        rec.append(hits / len(rel))
    prec, rec = np.array(prec), np.array(rec)
    out = np.zeros(levels)
    for j, r in enumerate(pts):
        mask = rec >= r
        out[j] = prec[mask].max() if mask.any() else 0.0
    return out


METRICS = {
    "MAP": average_precision,
    "P@5": lambda r, q: precision_at(r, q, 5),
    "P@10": lambda r, q: precision_at(r, q, 10),
    "R@100": lambda r, q: recall_at(r, q, 100),
    "nDCG@10": lambda r, q: ndcg_at(r, q, 10),
    "MRR": reciprocal_rank,
    "R-Prec": r_precision,
    "BPref": bpref,
}


def evaluate_run(runs: Dict[str, List[str]], qrels: Dict[str, Dict[str, int]],
                 metrics: Dict = METRICS) -> Dict[str, Dict[str, float]]:
    """Per-query scores: {metric: {qid: value}} over queries that have judgements."""
    out: Dict[str, Dict[str, float]] = {m: {} for m in metrics}
    for qid, q in qrels.items():
        run = runs.get(qid, [])
        for m, fn in metrics.items():
            out[m][qid] = fn(run, q)
    return out


def mean_scores(per_query: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    return {m: float(np.mean(list(v.values()))) if v else 0.0 for m, v in per_query.items()}


# ---------------------------------------------------------------- significance testing
def paired_t_test(a: Sequence[float], b: Sequence[float]) -> float:
    from scipy import stats
    return float(stats.ttest_rel(a, b).pvalue)


def randomization_test(a: Sequence[float], b: Sequence[float], n: int = 10_000, seed: int = 0) -> float:
    """Two-sided paired randomisation (permutation) test (Smucker, Allan & Carterette, CIKM 2007)."""
    rng = np.random.default_rng(seed)
    d = np.asarray(a) - np.asarray(b)
    obs = abs(d.mean())
    signs = rng.choice([-1, 1], size=(n, len(d)))
    return float((np.abs((signs * d).mean(1)) >= obs - 1e-12).mean())
