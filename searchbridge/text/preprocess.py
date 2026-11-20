"""Text encoding pipeline (Syllabus Module 3).

Normalisation -> tokenisation -> stop-word removal -> stemming.
Each step is configurable so experiments can ablate them
(e.g. "does stemming help on Cranfield?").
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List

try:  # Porter (1980) stemmer; NLTK needs no corpus download for this.
    from nltk.stem import PorterStemmer as _Porter

    _STEMMER = _Porter()

    def _stem(tok: str) -> str:
        return _STEMMER.stem(tok)
except Exception:  # pragma: no cover - lightweight fallback
    _SUFFIXES = ("ational", "ization", "fulness", "ousness", "iveness", "ing", "edly",
                 "ed", "ies", "es", "ly", "s")

    def _stem(tok: str) -> str:
        for suf in _SUFFIXES:
            if tok.endswith(suf) and len(tok) - len(suf) >= 3:
                return tok[: -len(suf)]
        return tok

# SMART-style English stop list (trimmed). Kept in code so no downloads are needed.
STOPWORDS = frozenset("""
a about above after again against all also am an and any are aren't as at be because been
before being below between both but by can can't cannot could couldn't did didn't do does
doesn't doing don't down during each either few for from further had hadn't has hasn't have
haven't having he he'd he'll he's her here here's hers herself him himself his how how's i
i'd i'll i'm i've if in into is isn't it it's its itself let's may me might more most must
mustn't my myself no nor not of off on once only or other ought our ours ourselves out over
own same shall shan't she she'd she'll she's should shouldn't so some such than that that's
the their theirs them themselves then there there's these they they'd they'll they're they've
this those through to too under until up upon very was wasn't we we'd we'll we're we've were
weren't what what's when when's where where's which while who who's whom why why's will with
won't would wouldn't you you'd you'll you're you've your yours yourself yourselves
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


@dataclass(frozen=True)
class PreprocessConfig:
    lowercase: bool = True
    remove_stopwords: bool = True
    stem: bool = True
    min_token_len: int = 2
    split_hyphens: bool = True


def normalize(text: str) -> str:
    """Unicode NFKD fold (é -> e), lowercase."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def tokenize(text: str, split_hyphens: bool = True) -> List[str]:
    toks = _TOKEN_RE.findall(normalize(text))
    if split_hyphens:
        out: List[str] = []
        for t in toks:
            out.extend(p for p in re.split(r"[-']", t) if p)
        return out
    return toks


@lru_cache(maxsize=200_000)
def stem(token: str) -> str:
    return _stem(token)


class Analyzer:
    """Callable text analyzer shared by indexer and query processor
    (the *same* pipeline must be applied to both, IIR §2.2)."""

    def __init__(self, config: PreprocessConfig | None = None):
        self.config = config or PreprocessConfig()

    def __call__(self, text: str) -> List[str]:
        return self.analyze(text)

    def analyze(self, text: str) -> List[str]:
        c = self.config
        out = []
        for tok in tokenize(text, c.split_hyphens):
            if len(tok) < c.min_token_len:
                continue
            if c.remove_stopwords and tok in STOPWORDS:
                continue
            out.append(stem(tok) if c.stem else tok)
        return out

    def analyze_term(self, term: str) -> str:
        toks = self.analyze(term)
        return toks[0] if toks else ""


def ngrams(tokens: Iterable[str], n: int = 2) -> List[str]:
    toks = list(tokens)
    return [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]
