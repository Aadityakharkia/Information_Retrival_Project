"""Text classification (Syllabus Module 6; IIR Ch. 13-14).

* MultinomialNB   - Naive Bayes with Laplace smoothing, log-space (IIR Fig. 13.2)
* RocchioClassifier - nearest-centroid in tf-idf space (IIR §14.2)
* KNNClassifier   - cosine k-NN with similarity-weighted voting (IIR §14.3)
* SpamFilter      - NB specialised to spam/ham, with a decision threshold

Used in SearchBridge to auto-tag documents with topics (facets in the UI) and to filter
low-quality / spam pages crawled from the web.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Callable, Dict, List, Sequence, Tuple

import numpy as np


class MultinomialNB:
    def __init__(self, analyzer: Callable[[str], List[str]], alpha: float = 1.0):
        self.an, self.alpha = analyzer, alpha

    def fit(self, texts: Sequence[str], labels: Sequence[str]) -> "MultinomialNB":
        self.classes = sorted(set(labels))
        n = Counter(labels)
        self.prior = {c: math.log(n[c] / len(labels)) for c in self.classes}
        tf: Dict[str, Counter] = defaultdict(Counter)
        for t, y in zip(texts, labels):
            tf[y].update(self.an(t))
        self.vocab = set().union(*tf.values())
        V = len(self.vocab)
        self.cond: Dict[str, Dict[str, float]] = {}
        self.unk: Dict[str, float] = {}
        for c in self.classes:
            tot = sum(tf[c].values())
            self.cond[c] = {w: math.log((tf[c][w] + self.alpha) / (tot + self.alpha * V)) for w in tf[c]}
            self.unk[c] = math.log(self.alpha / (tot + self.alpha * V))
        return self

    def log_scores(self, text: str) -> Dict[str, float]:
        toks = [w for w in self.an(text) if w in self.vocab]
        return {c: self.prior[c] + sum(self.cond[c].get(w, self.unk[c]) for w in toks) for c in self.classes}

    def predict_proba(self, text: str) -> Dict[str, float]:
        s = self.log_scores(text)
        m = max(s.values())
        e = {c: math.exp(v - m) for c, v in s.items()}
        z = sum(e.values())
        return {c: v / z for c, v in e.items()}

    def predict(self, text: str) -> str:
        s = self.log_scores(text)
        return max(s, key=s.get)

    def top_features(self, cls: str, k: int = 10) -> List[str]:
        return [w for w, _ in sorted(self.cond[cls].items(), key=lambda x: -x[1])[:k]]


class SpamFilter(MultinomialNB):
    def __init__(self, analyzer, threshold: float = 0.9):
        super().__init__(analyzer)
        self.threshold = threshold

    def is_spam(self, text: str) -> bool:
        return self.predict_proba(text).get("spam", 0.0) >= self.threshold


class _VectorClassifier:
    def __init__(self, analyzer):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(analyzer=analyzer, sublinear_tf=True)

    def _fit_X(self, texts):
        return self.vec.fit_transform(texts)


class RocchioClassifier(_VectorClassifier):
    def fit(self, texts, labels):
        X = self._fit_X(texts)
        y = np.asarray(labels)
        self.classes = sorted(set(labels))
        C = np.vstack([np.asarray(X[y == c].mean(0)) for c in self.classes])
        self.centroids = C / np.linalg.norm(C, axis=1, keepdims=True)
        return self

    def predict(self, text: str) -> str:
        v = self.vec.transform([text]).toarray()[0]
        return self.classes[int(np.argmax(self.centroids @ v))]


class KNNClassifier(_VectorClassifier):
    def __init__(self, analyzer, k: int = 5):
        super().__init__(analyzer)
        self.k = k

    def fit(self, texts, labels):
        self.X = self._fit_X(texts)
        self.y = list(labels)
        return self

    def predict(self, text: str) -> str:
        sims = (self.X @ self.vec.transform([text]).T).toarray().ravel()
        idx = np.argsort(-sims)[: self.k]
        votes: Dict[str, float] = defaultdict(float)
        for i in idx:
            votes[self.y[i]] += sims[i]
        return max(votes, key=votes.get)


def accuracy_report(clf, texts: Sequence[str], labels: Sequence[str]) -> Tuple[float, Dict[str, Tuple[float, float, float]]]:
    """Accuracy + per-class (precision, recall, F1)."""
    preds = [clf.predict(t) for t in texts]
    acc = float(np.mean([p == y for p, y in zip(preds, labels)]))
    per = {}
    for c in sorted(set(labels)):
        tp = sum(p == c and y == c for p, y in zip(preds, labels))
        fp = sum(p == c and y != c for p, y in zip(preds, labels))
        fn = sum(p != c and y == c for p, y in zip(preds, labels))
        p_ = tp / (tp + fp) if tp + fp else 0.0
        r_ = tp / (tp + fn) if tp + fn else 0.0
        per[c] = (p_, r_, 2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0.0)
    return acc, per
