"""k-gram index for wildcard queries and spelling correction (IIR §3.2-3.3).

Operates on the *surface* (unstemmed) vocabulary so users' typed words can be corrected.
"""
from __future__ import annotations

import fnmatch
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Set, Tuple


def kgrams(term: str, k: int = 2) -> Set[str]:
    t = f"${term}$"
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein (optimal string alignment) distance."""
    prev2: List[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


class KGramIndex:
    def __init__(self, k: int = 2):
        self.k = k
        self.index: Dict[str, Set[str]] = defaultdict(set)
        self.freq: Counter = Counter()

    def build(self, tokens: Iterable[str]) -> "KGramIndex":
        for t in tokens:
            if t.isalpha() and len(t) > 1:
                if t not in self.freq:
                    for g in kgrams(t, self.k):
                        self.index[g].add(t)
                self.freq[t] += 1
        return self

    # ------------------------------------------------------------ wildcard
    def wildcard(self, pattern: str, limit: int = 50) -> List[str]:
        """e.g. 'aero*ic' -> k-grams {$a, ae, er, ro, ic, c$} -> intersect -> post-filter."""
        padded = f"${pattern}$"
        grams: Set[str] = set()
        for piece in re.split(r"[*?]", padded):      # '*' = any run of letters, '?' = exactly one letter
            grams |= {piece[i:i + self.k] for i in range(len(piece) - self.k + 1)}
        if not grams:
            return []
        cands = set.intersection(*(self.index.get(g, set()) for g in grams))
        hits = [t for t in cands if fnmatch.fnmatchcase(t, pattern)]
        return sorted(hits, key=lambda t: -self.freq[t])[:limit]

    # ------------------------------------------------------------ spelling
    def suggest(self, word: str, max_dist: int = 2, jaccard_min: float = 0.3, top: int = 3) -> List[Tuple[str, int]]:
        """Candidates by k-gram Jaccard overlap, ranked by (edit distance, -frequency)."""
        if word in self.freq:
            return [(word, 0)]
        q = kgrams(word, self.k)
        overlap: Counter = Counter()
        for g in q:
            for t in self.index.get(g, ()):
                overlap[t] += 1
        scored = []
        for t, ov in overlap.items():
            jac = ov / (len(q) + len(kgrams(t, self.k)) - ov)
            if jac >= jaccard_min:
                d = edit_distance(word, t)
                if d <= max_dist:
                    scored.append((d, -self.freq[t], t))
        scored.sort()
        return [(t, d) for d, _, t in scored[:top]]

    def correct_query(self, words: List[str]) -> Tuple[List[str], bool]:
        out, changed = [], False
        for w in words:
            if w in self.freq or not w.isalpha() or len(w) <= 2:
                out.append(w)
                continue
            s = self.suggest(w)
            if s and s[0][0] != w:
                out.append(s[0][0])
                changed = True
            else:
                out.append(w)
        return out, changed
