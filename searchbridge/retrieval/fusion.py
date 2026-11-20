"""Rank / score fusion for hybrid lexical + semantic retrieval.

* Reciprocal Rank Fusion  (Cormack, Clarke & Büttcher, SIGIR 2009)
* CombSUM / CombMNZ       (Fox & Shaw, TREC-2 1994) over min-max or z-score normalised scores
* Linear interpolation    alpha * lexical + (1 - alpha) * dense
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

Scores = Dict[int, float]


def normalize(scores: Scores, method: str = "minmax", depth: int | None = None) -> Scores:
    if not scores:
        return {}
    items = sorted(scores.items(), key=lambda kv: -kv[1])
    if depth:
        items = items[:depth]
    v = np.array([s for _, s in items], dtype=float)
    if method == "minmax":
        lo, hi = v.min(), v.max()
        v = (v - lo) / (hi - lo) if hi > lo else np.ones_like(v)
    elif method == "zscore":
        sd = v.std()
        v = (v - v.mean()) / sd if sd > 0 else np.zeros_like(v)
    return {d: float(x) for (d, _), x in zip(items, v)}


def rrf(runs: List[Scores], k: int = 60, depth: int = 1000) -> Scores:
    out: Scores = {}
    for run in runs:
        ranked = sorted(run.items(), key=lambda kv: -kv[1])[:depth]
        for r, (d, _) in enumerate(ranked, 1):
            out[d] = out.get(d, 0.0) + 1.0 / (k + r)
    return out


def comb_sum(runs: List[Scores], weights: List[float] | None = None, norm: str = "minmax",
             depth: int = 1000, mnz: bool = False) -> Scores:
    weights = weights or [1.0] * len(runs)
    out: Scores = {}
    hits: Dict[int, int] = {}
    for w, run in zip(weights, runs):
        for d, s in normalize(run, norm, depth).items():
            out[d] = out.get(d, 0.0) + w * s
            hits[d] = hits.get(d, 0) + 1
    if mnz:
        out = {d: s * hits[d] for d, s in out.items()}
    return out


def interpolate(lexical: Scores, dense: Scores, alpha: float, depth: int = 1000) -> Scores:
    return comb_sum([lexical, dense], [alpha, 1 - alpha], "minmax", depth)
