"""Responsible IR (Syllabus Module 9): diversity, bias auditing and fair exposure.

* MMR re-ranking (Carbonell & Goldstein, SIGIR 1998) - reduces redundancy, filter bubbles
* Exposure audit: share of position-discounted attention each group (source, venue,
  author, region...) receives in a ranking (Singh & Joachims, KDD 2018)
* Fair re-ranking: greedy re-ranking that keeps every group's exposure close to its share
  of *relevance* (equity of attention, Biega et al., SIGIR 2018) while preserving utility.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np

Ranked = List[Tuple[int, float]]


def mmr(candidates: Ranked, emb: np.ndarray, lam: float = 0.7, k: int = 10) -> Ranked:
    """argmax_d  lam*rel(d) - (1-lam)*max_{s in S} sim(d, s);  rel min-max normalised."""
    if not candidates:
        return []
    scores = np.array([s for _, s in candidates], float)
    rel = (scores - scores.min()) / (np.ptp(scores) or 1)
    ids = [d for d, _ in candidates]
    V = emb[ids]
    selected: List[int] = []
    remaining = list(range(len(ids)))
    while remaining and len(selected) < k:
        if selected:
            red = (V[remaining] @ V[selected].T).max(1)
        else:
            red = np.zeros(len(remaining))
        mm = lam * rel[remaining] - (1 - lam) * red
        j = remaining[int(np.argmax(mm))]
        selected.append(j)
        remaining.remove(j)
    return [(ids[j], float(scores[j])) for j in selected]


def position_weight(rank: int) -> float:
    return 1.0 / math.log2(rank + 1)


def exposure_by_group(ranking: Sequence[int], group_of: Callable[[int], str], k: int = 10) -> Dict[str, float]:
    exp: Dict[str, float] = defaultdict(float)
    for r, d in enumerate(ranking[:k], 1):
        exp[group_of(d)] += position_weight(r)
    z = sum(exp.values()) or 1
    return {g: v / z for g, v in exp.items()}


def exposure_disparity(ranking: Ranked, group_of: Callable[[int], str], k: int = 10) -> Dict[str, float]:
    """Per group: exposure share - relevance share (0 = perfectly proportional)."""
    rel: Dict[str, float] = defaultdict(float)
    for d, s in ranking[:k]:
        rel[group_of(d)] += max(s, 0)
    zr = sum(rel.values()) or 1
    exp = exposure_by_group([d for d, _ in ranking], group_of, k)
    return {g: exp.get(g, 0) - rel[g] / zr for g in set(rel) | set(exp)}


def fair_rerank(candidates: Ranked, group_of: Callable[[int], str], k: int = 10, tradeoff: float = 0.5) -> Ranked:
    """Greedy: at each position pick the doc maximising
    (1-t)*norm_score + t*(target_exposure_deficit of its group)."""
    if not candidates:
        return []
    s = np.clip(np.array([x for _, x in candidates], float), 0, None)
    norm = s / (s.max() or 1)          # ratio-scaled so relevance shares stay proportional
    rel_share: Dict[str, float] = defaultdict(float)
    for (d, _), n in zip(candidates, norm):
        rel_share[group_of(d)] += n + 1e-9
    tot = sum(rel_share.values())
    target = {g: v / tot for g, v in rel_share.items()}
    got: Dict[str, float] = defaultdict(float)
    pool = list(range(len(candidates)))
    out: Ranked = []
    for r in range(1, min(k, len(pool)) + 1):
        z = sum(got.values()) + position_weight(r)
        best = max(pool, key=lambda i: (1 - tradeoff) * norm[i]
                   + tradeoff * (target[group_of(candidates[i][0])] - got[group_of(candidates[i][0])] / z))
        g = group_of(candidates[best][0])
        got[g] += position_weight(r)
        out.append(candidates[best])
        pool.remove(best)
    return out


def intra_list_diversity(ranking: Sequence[int], emb: np.ndarray, k: int = 10) -> float:
    ids = list(ranking[:k])
    if len(ids) < 2:
        return 0.0
    S = emb[ids] @ emb[ids].T
    n = len(ids)
    return float(1 - (S.sum() - np.trace(S)) / (n * (n - 1)))
