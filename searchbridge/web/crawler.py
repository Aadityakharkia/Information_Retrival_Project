"""Polite web spider (Syllabus Module 7; IIR Ch. 20) + near-duplicate detection (IIR §19.6).

Features: URL frontier (BFS, per-host queues), robots.txt compliance, per-host politeness
delay, URL normalisation, domain allow-list, max pages / depth, content-type filter,
exact-duplicate (hash) and near-duplicate (MinHash over word shingles) elimination.
The fetch function is injectable, which makes the crawler unit-testable offline.
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple  # noqa: F401

import numpy as np

from ..documents import Document, parse_html

import os as _os

# Sites such as Wikipedia ask bots to identify themselves with contact details: set SEARCHBRIDGE_CONTACT
# to an email address or URL and it is added to the User-Agent.
UA = "SearchBridgeBot/1.0 (CSD358 student information-retrieval project; polite crawler, 1 request/s" + (
    f"; {_os.environ['SEARCHBRIDGE_CONTACT']})" if _os.environ.get("SEARCHBRIDGE_CONTACT") else ")")


# ------------------------------------------------------------------ near duplicates
def shingles(text: str, w: int = 4) -> Set[str]:
    toks = text.lower().split()
    return {" ".join(toks[i:i + w]) for i in range(max(len(toks) - w + 1, 1))}


class MinHasher:
    def __init__(self, num_perm: int = 128, seed: int = 1):
        rng = np.random.default_rng(seed)
        self.p = (1 << 61) - 1
        self.a = rng.integers(1, self.p, num_perm, dtype=np.uint64)
        self.b = rng.integers(0, self.p, num_perm, dtype=np.uint64)

    def signature(self, sh: Set[str]) -> np.ndarray:
        hv = np.array([int(hashlib.md5(s.encode()).hexdigest()[:15], 16) for s in sh], dtype=np.uint64)
        return ((np.outer(hv, self.a) + self.b) % np.uint64(self.p)).min(0)

    @staticmethod
    def similarity(s1: np.ndarray, s2: np.ndarray) -> float:
        return float((s1 == s2).mean())


class LSHIndex:
    """Banded locality-sensitive hashing over MinHash signatures (Broder 1997; IIR §19.6):
    near-duplicate candidates are found in ~O(1) per page instead of comparing with every page."""

    def __init__(self, bands: int = 32, rows: int = 4):
        self.bands, self.rows = bands, rows
        self.buckets: List[Dict[bytes, List[int]]] = [dict() for _ in range(bands)]
        self.sigs: List[np.ndarray] = []

    def candidates(self, sig: np.ndarray) -> Set[int]:
        out: Set[int] = set()
        for b in range(self.bands):
            out.update(self.buckets[b].get(sig[b * self.rows:(b + 1) * self.rows].tobytes(), ()))
        return out

    def add(self, sig: np.ndarray) -> int:
        i = len(self.sigs)
        self.sigs.append(sig)
        for b in range(self.bands):
            self.buckets[b].setdefault(sig[b * self.rows:(b + 1) * self.rows].tobytes(), []).append(i)
        return i

    def query(self, sig: np.ndarray, threshold: float) -> Optional[int]:
        for c in self.candidates(sig):
            if MinHasher.similarity(sig, self.sigs[c]) >= threshold:
                return c
        return None


def jaccard(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


# ------------------------------------------------------------------ crawler
def normalize_url(base: str, href: str) -> Optional[str]:
    url = urllib.parse.urljoin(base, href)
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https"):
        return None
    # percent-encode non-ASCII characters (e.g. an en dash in a title) so the URL can be fetched;
    # already-encoded %XX sequences are kept as they are
    path = urllib.parse.quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(p.query, safe="=&%:@!$'()*+,;/?-._~")
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), path, query, ""))


def default_fetch(url: str, timeout: float = 10.0) -> Tuple[int, str, str]:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read(2_000_000).decode("utf-8", "ignore")


@dataclass
class CrawlConfig:
    max_pages: int = 100
    max_depth: int = 3
    delay_s: float = 1.0
    allowed_domains: Optional[Set[str]] = None
    near_dup_threshold: float = 0.9
    honour_crawl_delay: bool = True
    path_prefix: Optional[str] = None          # stay inside e.g. "/wiki/"
    exclude: Tuple[str, ...] = ()              # skip URLs containing any of these substrings


@dataclass
class Crawler:
    config: CrawlConfig = field(default_factory=CrawlConfig)
    fetch: Callable[[str], Tuple[int, str, str]] = default_fetch
    robots_fetch: Optional[Callable[[str], str]] = None
    on_page: Optional[Callable[[str, str, List[str]], None]] = None   # (url, raw_html, out_links) hook for parsers

    def __post_init__(self):
        self._robots: Dict[str, urllib.robotparser.RobotFileParser] = {}
        self._last_hit: Dict[str, float] = {}
        self.mh = MinHasher()
        self.lsh = LSHIndex()
        self.stats = {"fetched": 0, "robots_blocked": 0, "out_of_scope": 0, "dup_exact": 0, "dup_near": 0, "errors": 0}
        self.blocked_urls: List[str] = []
        self.error_examples: List[str] = []

    def in_scope(self, url: str) -> bool:
        """Path prefix and exclusions apply to the path and query only (every URL has ':' in 'https://')."""
        parts = urllib.parse.urlsplit(url)
        if self.config.allowed_domains and not any(parts.netloc.endswith(d) for d in self.config.allowed_domains):
            return False          # other sites (e.g. other-language Wikipedias) are out of scope, not robots-blocked
        if self.config.path_prefix and not parts.path.startswith(self.config.path_prefix):
            return False
        local = urllib.parse.unquote(parts.path) + ("?" + parts.query if parts.query else "")
        return not any(x and x in local for x in self.config.exclude)

    def allowed(self, url: str) -> bool:
        host = urllib.parse.urlsplit(url).netloc
        if self.config.allowed_domains and not any(host.endswith(d) for d in self.config.allowed_domains):
            return False
        rp = self._robots.get(host)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"{urllib.parse.urlsplit(url).scheme}://{host}/robots.txt"
            try:
                txt = self.robots_fetch(robots_url) if self.robots_fetch else self.fetch(robots_url)[2]
                rp.parse(txt.splitlines())
            except Exception:
                rp.parse([])  # unreachable robots.txt => allow
            self._robots[host] = rp
        return rp.can_fetch(UA, url)

    def _polite_wait(self, host: str) -> None:
        delay = self.config.delay_s
        rp = self._robots.get(host)
        if self.config.honour_crawl_delay and rp is not None:
            cd = rp.crawl_delay(UA)
            if cd is not None:
                delay = max(delay, float(cd))
        wait = delay - (time.time() - self._last_hit.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.time()

    def crawl(self, seeds: Iterable[str]) -> List[Document]:
        frontier = deque((normalize_url(s, ""), 0) for s in seeds)
        seen: Set[str] = {u for u, _ in frontier}
        hashes: Set[str] = set()
        docs: List[Document] = []
        while frontier and len(docs) < self.config.max_pages:
            url, depth = frontier.popleft()
            if not self.in_scope(url):
                self.stats["out_of_scope"] += 1
                continue
            if not self.allowed(url):
                self.stats["robots_blocked"] += 1
                self.blocked_urls.append(url)
                continue
            self._polite_wait(urllib.parse.urlsplit(url).netloc)
            try:
                status, ctype, body = self.fetch(url)
            except Exception as ex:
                self.stats["errors"] += 1
                if len(self.error_examples) < 5:
                    self.error_examples.append(f"{url}: {ex}")
                continue
            if status != 200 or "html" not in ctype:
                self.stats["errors"] += 1
                if len(self.error_examples) < 5:
                    self.error_examples.append(f"{url}: HTTP {status} {ctype}")
                continue
            self.stats["fetched"] += 1
            title, text, hrefs = parse_html(body)
            h = hashlib.sha1(text.encode()).hexdigest()
            if h in hashes:
                self.stats["dup_exact"] += 1
                continue
            sig = self.mh.signature(shingles(text))
            if self.lsh.query(sig, self.config.near_dup_threshold) is not None:
                self.stats["dup_near"] += 1
                continue
            hashes.add(h)
            self.lsh.add(sig)
            out_links = [u for u in (normalize_url(url, x) for x in hrefs) if u]
            if self.on_page:
                self.on_page(url, body, out_links)
            docs.append(Document(url, title or url, text, {"source": url, "type": "web"}, out_links))
            if depth < self.config.max_depth:
                for u in out_links:
                    if u not in seen:
                        seen.add(u)
                        frontier.append((u, depth + 1))
        return docs
