"""Bounded personal re-ranking.

final(d) = relevance(d) + beta * gate(relevance(d)) * p(d),    p(d) in [-1, 1]

relevance is min-max normalised over the candidate pool, so it stays the primary factor: a document
the profile loves can move up by at most beta, and the gate removes the boost from documents that are
not relevant to the current query at all.

p(d) = 0.5 * affinity(d)                       what the user did with this document before
     + 0.2 * interest(d)                       closeness to the user's interest vector (embedding centroid
                                               of documents they found useful)
     + 0.2 * query_association(d)              the document was useful for a similar earlier query
     + 0.1 * link_neighbourhood(d)             cited by / linking to a document the user explored by
                                               following links (graph structure x actual navigation)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from .profile import Profile

COMPONENT_WEIGHTS = {"affinity": 0.5, "interest": 0.2, "query": 0.2, "links": 0.1}
DEFAULT_BETA = 0.5      # chosen by 2-fold CV on the simulated-user benchmark; grid capped at 0.5 so relevance (range 1) stays the larger term
GATE = 0.3


@dataclass
class PersonalContext:
    profile: Profile
    doc_index: Dict[str, int]
    emb: np.ndarray
    analyzer: Callable[[str], List[str]]
    out_links: Callable[[int], Sequence[int]]
    in_links: Callable[[int], Sequence[int]]
    beta: float = DEFAULT_BETA
    _assoc: Optional[List[Tuple[Set[str], int, float]]] = field(default=None, repr=False)
    _interest: Optional[np.ndarray] = field(default=None, repr=False)
    _nbrs: Optional[Dict[int, float]] = field(default=None, repr=False)

    @property
    def key(self) -> str:
        return f"{self.profile.user}:{self.profile.version}:{self.beta}"

    def _idx(self, doc: str) -> Optional[int]:
        return self.doc_index.get(doc)

    def interest(self) -> Optional[np.ndarray]:
        if self._interest is None:
            pos = [(self._idx(d), a) for d, a in self.profile.positive().items() if self._idx(d) is not None]
            if not pos:
                return None
            v = sum(a * self.emb[i] for i, a in pos)
            n = np.linalg.norm(v)
            self._interest = v / n if n else None
        return self._interest

    def associations(self) -> List[Tuple[Set[str], int, float]]:
        if self._assoc is None:
            self._assoc = [(set(self.analyzer(q)), self._idx(d), w) for q, d, w in self.profile.query_docs if self._idx(d) is not None]
        return self._assoc

    def neighbourhood(self) -> Dict[int, float]:
        if self._nbrs is None:
            out: Dict[int, float] = {}
            for d, w in self.profile.explored.items():
                i = self._idx(d)
                if i is None or self.profile.affinity.get(d, 0) <= 0:
                    continue
                for j in list(self.out_links(i)) + list(self.in_links(i)):
                    out[j] = max(out.get(j, 0.0), min(1.0, w))
            self._nbrs = out
        return self._nbrs

    def score(self, cands: Sequence[int], q_terms: Sequence[str], docs_ids: Sequence[str]) -> Dict[int, Tuple[float, Dict[str, float], List[str]]]:
        """p(d), its components and human-readable reasons for each candidate."""
        q = set(q_terms)
        u = self.interest()
        sims = self.emb[list(cands)] @ u if u is not None and len(cands) else None
        if sims is not None:
            med, mx = float(np.median(sims)), float(sims.max())
            inter = np.clip((sims - med) / (mx - med), 0, 1) if mx > med else np.zeros_like(sims)
        assoc = self.associations()
        nb = self.neighbourhood()
        explored_idx = {self._idx(x) for x in self.profile.explored}
        out = {}
        for j, d in enumerate(cands):
            doc = docs_ids[d]
            a = self.profile.affinity.get(doc, 0.0)
            qa = 0.0
            for terms, i, w in assoc:
                if i == d and terms and q:
                    qa = max(qa, len(terms & q) / len(terms | q) * min(1.0, w))
            ln = nb.get(d, 0.0) if d not in explored_idx else 0.0
            # the interest vector generalises to OTHER documents; a document's own history is already in `affinity`
            own = doc in self.profile.affinity
            comp = {"affinity": a, "interest": float(inter[j]) if sims is not None and not own else 0.0, "query": qa, "links": ln}
            p = float(np.clip(sum(COMPONENT_WEIGHTS[k] * v for k, v in comp.items()), -1, 1))
            if abs(p) < 1e-4:
                continue
            reasons = list(self.profile.evidence[doc].reasons()) if doc in self.profile.evidence else []
            if qa > 0.2:
                reasons.append("Useful for a similar search before")
            if ln > 0:
                reasons.append("Linked to a document you explored")
            if comp["interest"] > 0.6 and not reasons:
                reasons.append("Close to topics you read")
            out[d] = (p, comp, reasons)
        return out


def gate(rel: float) -> float:
    return min(1.0, max(0.0, rel) / GATE)


def apply(base: Dict[int, float], personal: Dict[int, Tuple[float, Dict[str, float], List[str]]], beta: float) -> Dict[int, float]:
    """base: normalised relevance in [0, 1]."""
    out = dict(base)
    for d, (p, _, _) in personal.items():
        if d in out:
            out[d] = base[d] + beta * (gate(base[d]) if p > 0 else 1.0) * p
    return out
