"""Query-biased snippet generation and term highlighting (IIR §8.7)."""
from __future__ import annotations

import html
import re
from typing import Sequence

from .text.preprocess import Analyzer, stem

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def snippet(text: str, q_terms: Sequence[str], analyzer: Analyzer, max_chars: int = 260) -> str:
    """Pick the window of consecutive sentences covering the most distinct query terms."""
    qs = set(q_terms)
    sents = [s.strip() for s in _SENT.split(text) if s.strip()]
    if not sents:
        return text[:max_chars]
    best, best_score = 0, -1.0
    for i in range(len(sents)):
        window = " ".join(sents[i:i + 2])
        toks = analyzer(window)
        cover = len(qs & set(toks))
        dens = sum(t in qs for t in toks) / (len(toks) or 1)
        score = cover + 0.5 * dens - 0.01 * i
        if score > best_score:
            best, best_score = i, score
    out = " ".join(sents[best:best + 2])
    return (out[:max_chars].rsplit(" ", 1)[0] + " …") if len(out) > max_chars else out


def highlight(text: str, q_terms: Sequence[str], tag: str = "mark", stemmed: bool = True) -> str:
    qs = set(q_terms)

    def repl(m):
        w = m.group(0)
        key = stem(w.lower()) if stemmed else w.lower()
        return f"<{tag}>{w}</{tag}>" if key in qs else w

    return re.sub(r"[A-Za-z0-9]+", repl, html.escape(text))
