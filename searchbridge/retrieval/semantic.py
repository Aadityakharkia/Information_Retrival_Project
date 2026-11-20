"""Semantic (dense) retrieval.

Two interchangeable encoders behind one interface:
* LSAEncoder   - Latent Semantic Analysis: TF-IDF -> truncated SVD (Deerwester et al., 1990).
                 Fully offline, no downloads; the default.
* SBERTEncoder - Sentence-BERT bi-encoder (Reimers & Gurevych, 2019), e.g. all-MiniLM-L6-v2.
                 Used automatically when `sentence-transformers` is installed and the model
                 can be downloaded (`encoder="auto"`).

Documents are embedded once; queries are scored by cosine similarity (brute force is
exact and fast for ≤1e5 docs; swap in FAISS/HNSW for larger collections).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

import numpy as np

from .lexical import Ranked, top_k

log = logging.getLogger(__name__)


def _l2norm(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


class LSAEncoder:
    name = "LSA"

    def __init__(self, analyzer, dim: int = 200, seed: int = 42):
        self.analyzer, self.dim, self.seed = analyzer, dim, seed

    def fit(self, texts: List[str]) -> np.ndarray:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.vec = TfidfVectorizer(analyzer=self.analyzer, sublinear_tf=True, min_df=1)
        X = self.vec.fit_transform(texts)
        dim = min(self.dim, X.shape[1] - 1, X.shape[0] - 1)
        self.svd = TruncatedSVD(n_components=max(dim, 2), random_state=self.seed)
        return _l2norm(self.svd.fit_transform(X))

    def encode(self, texts: List[str]) -> np.ndarray:
        return _l2norm(self.svd.transform(self.vec.transform(texts)))


class SBERTEncoder:
    """Loads the transformer lazily and drops it when pickled, so saved indexes stay small
    and portable; it is re-loaded from the local Hugging Face cache on first query."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.name = f"SBERT ({model_name.split('/')[-1]})"
        self._model = None
        _ = self.model   # fail fast if the package or model is unavailable

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def __getstate__(self):
        return {"model_name": self.model_name, "name": self.name, "_model": None}

    def fit(self, texts: List[str]) -> np.ndarray:
        return self.encode(texts)

    def encode(self, texts: List[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, batch_size=64, normalize_embeddings=True,
                                            show_progress_bar=False))


def make_encoder(kind: str, analyzer, **kw):
    if kind in ("sbert", "auto"):
        try:
            return SBERTEncoder(kw.get("model_name", "sentence-transformers/all-MiniLM-L6-v2"))
        except Exception as e:  # no package / no network
            if kind == "sbert":
                raise
            log.info("SBERT unavailable (%s); falling back to LSA", e)
    return LSAEncoder(analyzer, dim=kw.get("dim", 200))


class DenseRetriever:
    def __init__(self, encoder, texts: List[str], live_mask: Optional[Sequence[bool]] = None):
        self.encoder = encoder
        self.name = f"Dense ({encoder.name})"
        self.emb = encoder.fit(texts).astype(np.float32)

    def query_vector(self, text: str) -> np.ndarray:
        return self.encoder.encode([text])[0]

    def score_text(self, text: str) -> Dict[int, float]:
        sims = self.emb @ self.query_vector(text)
        return {i: float(s) for i, s in enumerate(sims)}

    def search_text(self, text: str, k: int = 10) -> Ranked:
        return top_k(self.score_text(text), k)

    def similar_docs(self, doc: int, k: int = 5) -> Ranked:
        sims = self.emb @ self.emb[doc]
        sims[doc] = -np.inf
        idx = np.argpartition(-sims, k)[:k]
        return sorted(((int(i), float(sims[i])) for i in idx), key=lambda x: -x[1])
