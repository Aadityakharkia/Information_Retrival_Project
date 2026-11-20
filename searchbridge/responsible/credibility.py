"""Credibility & misinformation signals (Syllabus Module 9: handling fake news).

A transparent, feature-based credibility score in [0, 1] — deliberately *explainable*
rather than a black box, so users see why a result is flagged:
  + scholarly signals : references/DOI/citations, numbers with units, hedged language
  + source signal     : domain reputation table (configurable allow/deny lists)
  + graph signal      : authority from PageRank (well-cited documents)
  - sensational cues  : clickbait phrases, excessive '!' or ALL-CAPS, absolutist claims
Inspired by feature sets in Castillo et al. (WWW 2011) and Horne & Adali (ICWSM 2017).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

CLICKBAIT = re.compile(r"\b(you won'?t believe|shocking|miracle|secret they|100% (guaranteed|proven)|"
                       r"doctors hate|breaking!|exposed|must see|goes viral)\b", re.I)
ABSOLUTE = re.compile(r"\b(always|never|everyone|no one|proven fact|undeniable|cure[sd]?)\b", re.I)
HEDGE = re.compile(r"\b(may|might|suggests?|appears?|approximately|estimated|indicates?|likely)\b", re.I)
SCHOLARLY = re.compile(r"(doi:|10\.\d{4,}/|et al\.|\[\d+\]|references|bibliography|\(\d{4}\))", re.I)
QUANT = re.compile(r"\b\d+(\.\d+)?\s?(%|mm|cm|km|kg|ms|hz|mach|deg|k|psi|ft)\b", re.I)

DEFAULT_DOMAINS = {"arxiv.org": 0.9, "acm.org": 0.95, "ieee.org": 0.95, "nature.com": 0.95,
                   "gov": 0.85, "edu": 0.85, "ac.in": 0.85, "wikipedia.org": 0.75}


@dataclass
class CredibilityScore:
    score: float
    reasons: List[Tuple[str, float]]

    @property
    def flag(self) -> Optional[str]:
        return "low-credibility" if self.score < 0.35 else None


def credibility(text: str, source: str = "", authority: float = 0.0,
                domains: Dict[str, float] = DEFAULT_DOMAINS) -> CredibilityScore:
    words = max(len(text.split()), 1)
    reasons: List[Tuple[str, float]] = []
    s = 0.5

    def add(name, v):
        nonlocal s
        if abs(v) > 1e-6:
            reasons.append((name, round(v, 3)))
            s += v

    add("scholarly markers", min(len(SCHOLARLY.findall(text)) * 0.04, 0.15))
    add("quantitative evidence", min(len(QUANT.findall(text)) / words * 20, 0.1))
    add("hedged language", min(len(HEDGE.findall(text)) / words * 10, 0.08))
    add("clickbait phrases", -min(len(CLICKBAIT.findall(text)) * 0.15, 0.4))
    add("absolutist claims", -min(len(ABSOLUTE.findall(text)) / words * 15, 0.15))
    caps = sum(w.isupper() and len(w) > 3 for w in text.split()) / words
    add("ALL-CAPS shouting", -min(caps * 3, 0.15))
    add("exclamation marks", -min(text.count("!") / words * 20, 0.15))
    for dom, rep in domains.items():
        if source and (source.endswith(dom) or f".{dom}" in source or f"{dom}/" in source):
            add(f"source reputation ({dom})", (rep - 0.5) * 0.4)
            break
    add("citation authority (PageRank)", min(authority, 1.0) * 0.1)
    return CredibilityScore(max(0.0, min(1.0, s)), reasons)
