"""Zipf's law and Heaps' law fits (IIR §5.1) + postings size estimation."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List, Tuple

import numpy as np


@dataclass
class ZipfFit:
    exponent: float      # s in cf_i ∝ i^-s (ideal ≈ 1)
    r2: float


@dataclass
class HeapsFit:
    k: float             # M = k * T^b
    b: float
    r2: float


def _loglog_fit(x: np.ndarray, y: np.ndarray) -> Tuple[float, float, float]:
    lx, ly = np.log10(x), np.log10(y)
    slope, intercept = np.polyfit(lx, ly, 1)
    pred = slope * lx + intercept
    r2 = 1 - ((ly - pred) ** 2).sum() / ((ly - ly.mean()) ** 2).sum()
    return slope, intercept, r2


def zipf_fit(cf: Counter) -> Tuple[ZipfFit, np.ndarray, np.ndarray]:
    freqs = np.array(sorted(cf.values(), reverse=True), dtype=float)
    ranks = np.arange(1, len(freqs) + 1, dtype=float)
    slope, _, r2 = _loglog_fit(ranks, freqs)
    return ZipfFit(-slope, r2), ranks, freqs


def heaps_fit(token_stream: Iterable[str], samples: int = 50) -> Tuple[HeapsFit, np.ndarray, np.ndarray]:
    seen, T_pts, M_pts = set(), [], []
    toks = list(token_stream)
    step = max(len(toks) // samples, 1)
    for i, t in enumerate(toks, 1):
        seen.add(t)
        if i % step == 0:
            T_pts.append(i)
            M_pts.append(len(seen))
    T, M = np.array(T_pts, float), np.array(M_pts, float)
    b, logk, r2 = _loglog_fit(T, M)
    return HeapsFit(10 ** logk, b, r2), T, M


def estimate_postings(num_docs: int, num_tokens: int, vocab: int) -> List[Tuple[str, float]]:
    """Back-of-envelope estimates that students can compare against measured sizes."""
    return [("Avg postings per term", num_tokens / max(vocab, 1)),
            ("Avg distinct terms per doc (upper bound)", num_tokens / max(num_docs, 1)),
            ("Uncompressed docID postings (MB, 4B ints, ≤1 per token)", 4 * num_tokens / 1e6)]
