"""Privacy-preserving search (Syllabus Module 9).

* PII detection/redaction for snippets and stored query logs (emails, phones, Aadhaar-like
  12-digit IDs, PAN, credit-card numbers with Luhn check, IPs).
* Query-log anonymisation: salted hashing of user ids + k-anonymity filter on queries
  (only release queries issued by >= k distinct users; cf. the AOL log incident, 2006).
* Differentially-private query counts via the Laplace mechanism (Dwork et al., 2006).
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

_PII = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
    "PHONE": re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9}\d(?!\d)"),
    "AADHAAR": re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "PAN": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "CARD": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "IP": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}


def _luhn(num: str) -> bool:
    digits = [int(c) for c in num if c.isdigit()][::-1]
    total = sum(d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(digits))
    return total % 10 == 0


def find_pii(text: str) -> List[Tuple[str, str]]:
    hits = []
    for label in ("EMAIL", "PAN", "IP", "CARD", "AADHAAR", "PHONE"):
        for m in _PII[label].finditer(text):
            if label == "CARD" and not _luhn(m.group()):
                continue
            hits.append((label, m.group()))
    return hits


def redact(text: str) -> str:
    for label, value in sorted(find_pii(text), key=lambda x: -len(x[1])):
        text = text.replace(value, f"[{label}]")
    return text


@dataclass
class QueryLog:
    salt: str = "change-me"
    k_anonymity: int = 3
    _records: List[Tuple[str, str]] = field(default_factory=list)

    def log(self, user_id: str, query: str) -> None:
        uid = hashlib.sha256((self.salt + user_id).encode()).hexdigest()[:16]
        self._records.append((uid, redact(query.strip().lower())))

    def releasable_queries(self) -> Dict[str, int]:
        users = defaultdict(set)
        for u, q in self._records:
            users[q].add(u)
        return {q: len(u) for q, u in users.items() if len(u) >= self.k_anonymity}

    def dp_counts(self, epsilon: float = 1.0, seed: Optional[int] = None) -> Dict[str, float]:
        """Laplace(1/epsilon) noise on per-query user counts (sensitivity 1 per user-query)."""
        rng = np.random.default_rng(seed)
        return {q: max(0.0, c + rng.laplace(0, 1 / epsilon)) for q, c in self.releasable_queries().items()}
