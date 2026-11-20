"""Topical categorisation with Naive Bayes + vector-space (Rocchio, kNN) classifiers.

Used in three places:
  * documents without a topical category get one, but only when the classifiers are confident
    (Naive Bayes and Rocchio agree and the document is as close to the class centroid as typical
    training documents) - otherwise they stay uncategorised rather than being forced into a class;
  * query intent: a query that clearly belongs to one category gets a one-click category filter;
  * the Insights page reports held-out accuracy of all three classifiers.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .classify import KNNClassifier, MultinomialNB, RocchioClassifier, accuracy_report

NON_TOPICAL = ("abstract", "unknown", "other", "report", "journal", "proceedings")


def topical(label: str) -> bool:
    return bool(label) and not any(w in label.lower() for w in NON_TOPICAL)


class Categorizer:
    def __init__(self, analyzer: Callable[[str], List[str]], min_per_class: int = 15):
        self.analyzer, self.min_per_class = analyzer, min_per_class
        self.ok = False
        self.report: Dict = {}

    def fit(self, texts: Sequence[str], labels: Sequence[str], seed: int = 0) -> "Categorizer":
        counts = Counter(lab for lab in labels if topical(lab))
        keep = {c for c, n in counts.items() if n >= self.min_per_class}
        idx = [i for i, lab in enumerate(labels) if lab in keep]
        if len(keep) < 2:
            return self
        X, y = [texts[i] for i in idx], [labels[i] for i in idx]
        # held-out evaluation (stratified 80/20)
        rng = random.Random(seed)
        train, test = [], []
        for c in sorted(keep):
            m = [i for i, lab in enumerate(y) if lab == c]
            rng.shuffle(m)
            cut = max(1, len(m) // 5)
            test += m[:cut]
            train += m[cut:]
        tx, ty = [X[i] for i in train], [y[i] for i in train]
        vx, vy = [X[i] for i in test], [y[i] for i in test]
        models = {"Multinomial Naive Bayes": MultinomialNB(self.analyzer), "Rocchio (nearest centroid)": RocchioClassifier(self.analyzer),
                  "kNN (k=5, cosine)": KNNClassifier(self.analyzer, 5)}
        rep = {}
        for name, m in models.items():
            m.fit(tx, ty)
            acc, per = accuracy_report(m, vx, vy)
            preds = [m.predict(t) for t in vx]
            classes = sorted(keep)
            cm = [[sum(1 for p, t in zip(preds, vy) if t == a and p == b) for b in classes] for a in classes]
            rep[name] = {"accuracy": round(acc, 4), "macro_F1": round(float(np.mean([v[2] for v in per.values()])), 4), "confusion": cm}
        self.report = {"classes": sorted(keep), "train": len(tx), "test": len(vx),
                       "majority_baseline": round(Counter(vy).most_common(1)[0][1] / len(vy), 4), "models": rep}
        # final models on all labelled documents
        self.nb = MultinomialNB(self.analyzer).fit(X, y)
        self.rocchio = RocchioClassifier(self.analyzer).fit(X, y)
        Xv = self.rocchio.vec.transform(X)
        S = np.asarray(Xv @ self.rocchio.centroids.T)
        own = np.asarray([S[i, self.rocchio.classes.index(y[i])] for i in range(len(X))])
        self.min_sim = float(np.percentile(own, 10))   # as close to the centroid as 90 % of training docs
        self.classes = sorted(keep)
        self.ok = True
        return self

    def predict(self, text: str, min_prob: float = 0.9) -> Optional[Tuple[str, float]]:
        """(label, NB posterior) or None when the classifiers are not confident."""
        if not self.ok or not self.analyzer(text):
            return None
        probs = self.nb.predict_proba(text)
        label, p = max(probs.items(), key=lambda x: x[1])
        v = self.rocchio.vec.transform([text]).toarray()[0]
        sims = self.rocchio.centroids @ v
        best = self.rocchio.classes[int(np.argmax(sims))]
        if best != label or p < min_prob or float(sims.max()) < self.min_sim:
            return None
        return label, float(p)

    def query_intent(self, query: str) -> Optional[Tuple[str, float]]:
        """Short texts give weak evidence: require agreement and a clear posterior."""
        if not self.ok or len(self.analyzer(query)) == 0:
            return None
        probs = self.nb.predict_proba(query)
        ranked = sorted(probs.items(), key=lambda x: -x[1])
        v = self.rocchio.vec.transform([query]).toarray()[0]
        if not v.any():
            return None
        best = self.rocchio.classes[int(np.argmax(self.rocchio.centroids @ v))]
        if ranked[0][0] == best and ranked[0][1] >= 0.8 and (len(ranked) < 2 or ranked[0][1] - ranked[1][1] >= 0.5):
            return ranked[0]
        return None
