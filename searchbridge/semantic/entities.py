"""Entity recognition, linking & disambiguation (Syllabus Module 8).

Three complementary, dependency-free recognisers:
1. Pattern NER        - capitalised spans, ACRONYMS, codes like "NACA 0012", e-mails, years.
2. Collocation mining - statistically significant n-grams (PMI + frequency), which works on
                        lower-cased corpora such as Cranfield where capitalisation is lost.
3. Gazetteer linking  - maps mentions to ontology concepts via an alias table (SKOS-style
                        prefLabel / altLabel). Ambiguous mentions are disambiguated with a
                        simplified Lesk context-overlap score (Lesk 1986; cf. TagMe, Ferragina 2010).
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..text.preprocess import STOPWORDS, tokenize

_PATTERNS = {
    "CODE": re.compile(r"\b[A-Z]{2,}[- ]?\d{2,}[A-Z0-9-]*\b"),
    "ACRONYM": re.compile(r"\b[A-Z]{2,6}s?\b"),
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "YEAR": re.compile(r"\b(?:19|20)\d{2}\b"),
    "PROPER": re.compile(r"\b(?:[A-Z][a-z]+(?:\s+(?:of|de|van|von|the)?\s*[A-Z][a-z]+)+)\b"),
}


@dataclass
class Mention:
    text: str
    label: str
    start: int
    end: int
    concept: Optional[str] = None
    confidence: float = 1.0


def pattern_ner(text: str) -> List[Mention]:
    out: List[Mention] = []
    taken: List[Tuple[int, int]] = []
    for label, rx in _PATTERNS.items():
        for m in rx.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            if label == "ACRONYM" and m.group().lower() in STOPWORDS:
                continue
            taken.append((m.start(), m.end()))
            out.append(Mention(m.group(), label, m.start(), m.end()))
    return sorted(out, key=lambda m: m.start)


# academic boilerplate that produces cohesive but meaningless "phrases" (paper presents, et al, ...)
BOILERPLATE = frozenset("""paper papers present presents presented show shows shown describe describes described propose
proposes proposed approach approaches method methods study studies result results et al conference proceedings
international journal using based new used also general terms subject descriptors section figure fig table
author authors work works first second given well number case cases use technique techniques problem problems
example examples obtained found order paper's high low large small various different several""".split())


class CollocationMiner:
    """Bigram/trigram key-phrases scored by PMI, filtered by min frequency (Manning & Schütze ch.5)."""

    def __init__(self, min_count: int = 5, top: int = 500):
        self.min_count, self.top = min_count, top
        self.phrases: Dict[str, float] = {}

    def fit(self, texts: Iterable[str]) -> "CollocationMiner":
        uni, bi, tri = Counter(), Counter(), Counter()
        for t in texts:
            toks = tokenize(t)
            uni.update(toks)
            for i in range(len(toks) - 1):
                a, b = toks[i], toks[i + 1]
                if a in STOPWORDS or b in STOPWORDS or a.isdigit() or b.isdigit():
                    continue
                bi[(a, b)] += 1
                if i + 2 < len(toks) and toks[i + 2] not in STOPWORDS and not toks[i + 2].isdigit():
                    tri[(a, b, toks[i + 2])] += 1
        N = sum(uni.values())
        scored = {}
        for g, c in list(bi.items()) + list(tri.items()):
            if c < self.min_count or g[0] in BOILERPLATE or g[-1] in BOILERPLATE or len(g[0]) < 3 or len(g[-1]) < 3:
                continue
            pmi = math.log2(c * N ** (len(g) - 1) / math.prod(uni[w] for w in g))
            scored[" ".join(g)] = pmi * math.log(c)   # favour frequent *and* cohesive
        self.phrases = dict(sorted(scored.items(), key=lambda x: -x[1])[: self.top])
        return self

    def extract(self, text: str) -> List[str]:
        low = " ".join(tokenize(text))
        return [p for p in self.phrases if f" {p} " in f" {low} "]


@dataclass
class Concept:
    cid: str
    label: str
    aliases: List[str] = field(default_factory=list)
    broader: List[str] = field(default_factory=list)
    related: List[str] = field(default_factory=list)
    description: str = ""


class Ontology:
    def __init__(self, concepts: Sequence[Concept] = ()):
        self.concepts: Dict[str, Concept] = {c.cid: c for c in concepts}
        self.alias: Dict[str, Set[str]] = {}
        for c in concepts:
            for a in [c.label, *c.aliases]:
                self.alias.setdefault(" ".join(tokenize(a)), set()).add(c.cid)
        self.max_len = max((len(a.split()) for a in self.alias), default=1)

    @staticmethod
    def load(path: str | Path) -> "Ontology":
        data = json.loads(Path(path).read_text())
        return Ontology([Concept(**c) for c in data["concepts"]])

    def _context_score(self, cid: str, ctx: Set[str]) -> float:
        c = self.concepts[cid]
        sig = set(tokenize(" ".join([c.description, c.label, *c.aliases, *c.related])))
        return len(sig & ctx) / (len(sig) or 1)

    def link(self, text: str) -> List[Mention]:
        """Longest-match gazetteer lookup + Lesk disambiguation."""
        toks = tokenize(text)
        ctx = set(toks)
        out, i = [], 0
        while i < len(toks):
            for n in range(min(self.max_len, len(toks) - i), 0, -1):
                span = " ".join(toks[i:i + n])
                cands = self.alias.get(span)
                if cands:
                    scored = sorted(((self._context_score(c, ctx), c) for c in cands), reverse=True)
                    conf = 1.0 if len(cands) == 1 else scored[0][0] / (sum(s for s, _ in scored) or 1)
                    out.append(Mention(span, "CONCEPT", i, i + n, scored[0][1], conf))
                    i += n
                    break
            else:
                i += 1
        return out
