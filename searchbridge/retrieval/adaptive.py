"""QPP-Gated Adaptive Hybrid Retrieval (QAHR) — the project's main novel component.

Motivation
----------
Hybrid search usually mixes lexical (BM25) and semantic (dense) scores with ONE global
weight alpha (or with RRF). But the best mix is query dependent: precise, rare-term
queries ("NACA 0012 airfoil") favour exact matching, while vague or vocabulary-mismatched
queries favour semantic matching. Query Performance Prediction (QPP) signals estimate how
well each retriever is doing *for this query* without relevance judgements.

Method
------
1. For query q compute a feature vector phi(q):
     pre-retrieval : avgIDF, maxIDF, SCQ, SCS, |q|, OOV-ratio
     post-retrieval: NQC(BM25), NQC(dense), WIG(BM25), top-1 margin of each run,
                     RBO(BM25 top-20, dense top-20)   <- retriever agreement
2. Training: for each training query find the oracle alpha* on a grid that maximises AP
   (smoothed: AP-weighted mean of alphas within 98% of the best AP).
3. Learn alpha_hat(q) = clip(Ridge(phi(q)), 0, 1).
4. At query time: score = alpha_hat * minmax(BM25) + (1 - alpha_hat) * minmax(dense).
Evaluated with k-fold cross-validation over queries so no query is scored by a model
that saw its judgements.

Related work: Arabzadeh et al. (CIKM 2021) predicted *whether* to use dense or sparse
retrieval per query; QAHR instead regresses a continuous fusion weight from a richer
pre+post-retrieval QPP feature set including inter-retriever agreement (RBO).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from .fusion import interpolate
from .qpp import QPP

FEATURES = ["avg_idf", "max_idf", "avg_scq", "scs", "qlen", "oov",
            "nqc_lex", "nqc_dense", "wig_lex", "margin_lex", "margin_dense", "rbo"]
ALPHA_GRID = np.round(np.linspace(0, 1, 11), 2)


@dataclass
class AdaptiveModel:
    mean: List[float] = field(default_factory=lambda: [0.0] * len(FEATURES))
    std: List[float] = field(default_factory=lambda: [1.0] * len(FEATURES))
    coef: List[float] = field(default_factory=lambda: [0.0] * len(FEATURES))
    intercept: float = 0.5
    l2: float = 1.0

    def predict(self, x: np.ndarray) -> float:
        z = (x - np.array(self.mean)) / np.array(self.std)
        return float(np.clip(z @ np.array(self.coef) + self.intercept, 0.0, 1.0))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.__dict__, indent=2))

    @staticmethod
    def load(path: str | Path) -> "AdaptiveModel":
        return AdaptiveModel(**json.loads(Path(path).read_text()))


class AdaptiveHybrid:
    name = "QAHR (adaptive hybrid)"

    def __init__(self, qpp: QPP, model: Optional[AdaptiveModel] = None, depth: int = 1000):
        self.qpp, self.model, self.depth = qpp, model or AdaptiveModel(), depth

    # ---------------------------------------------------------------- features
    def features(self, q_terms: Sequence[str], lex: Dict[int, float], dense: Dict[int, float]) -> np.ndarray:
        f = self.qpp.pre(q_terms)
        lex_s = sorted(lex.values(), reverse=True)
        den_s = sorted(dense.values(), reverse=True)
        lex_mean = float(np.mean(lex_s[: self.depth])) if lex_s else 0.0
        den_mean = float(np.mean(den_s[: self.depth])) if den_s else 0.0
        f["nqc_lex"] = QPP.nqc(lex_s, lex_mean)
        f["nqc_dense"] = QPP.nqc(den_s, den_mean)
        f["wig_lex"] = QPP.wig(lex_s, lex_mean, int(f["qlen"]))
        f["margin_lex"] = (lex_s[0] - lex_s[1]) / (lex_s[0] + 1e-9) if len(lex_s) > 1 else 0.0
        f["margin_dense"] = (den_s[0] - den_s[1]) / (abs(den_s[0]) + 1e-9) if len(den_s) > 1 else 0.0
        top_l = [d for d, _ in sorted(lex.items(), key=lambda kv: -kv[1])[:20]]
        top_d = [d for d, _ in sorted(dense.items(), key=lambda kv: -kv[1])[:20]]
        f["rbo"] = QPP.rbo(top_l, top_d)
        return np.array([f[k] for k in FEATURES], dtype=float)

    def alpha(self, x: np.ndarray) -> float:
        return self.model.predict(x)

    def fuse(self, lex: Dict[int, float], dense: Dict[int, float], alpha: float) -> Dict[int, float]:
        return interpolate(lex, dense, alpha, self.depth)

    # ---------------------------------------------------------------- training
    @staticmethod
    def oracle_alpha(ap_by_alpha: Sequence[float], tol: float = 0.98) -> float:
        ap = np.asarray(ap_by_alpha)
        if ap.max() <= 0:
            return 0.5
        good = ap >= tol * ap.max()
        return float((ALPHA_GRID[good] * ap[good]).sum() / ap[good].sum())

    @staticmethod
    def fit(X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> AdaptiveModel:
        mean, std = X.mean(0), X.std(0)
        std[std == 0] = 1.0
        Z = (X - mean) / std
        A = Z.T @ Z + l2 * len(Z) * np.eye(Z.shape[1])
        coef = np.linalg.solve(A, Z.T @ (y - y.mean()))
        return AdaptiveModel(mean.tolist(), std.tolist(), coef.tolist(), float(y.mean()), l2)
