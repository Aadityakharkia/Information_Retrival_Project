"""Positional inverted index with SPIMI construction and dynamic (auxiliary) indexing.

Syllabus Module 3: index construction, merge sort of blocks, dynamic indexing,
positional indexes, postings size estimation.

Postings layout:  term -> {doc_int: [pos1, pos2, ...]}   (doc ints are dense 0..N-1)
"""
from __future__ import annotations

import heapq
import math
import pickle
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..text.preprocess import Analyzer

Postings = Dict[int, List[int]]


@dataclass
class IndexStats:
    num_docs: int
    num_terms: int
    num_postings: int
    num_tokens: int
    avg_doc_len: float


class InvertedIndex:
    def __init__(self, analyzer: Optional[Analyzer] = None, block_size: int = 50_000):
        self.analyzer = analyzer or Analyzer()
        self.block_size = block_size          # tokens per SPIMI block
        self.postings: Dict[str, Postings] = {}
        self.doc_ids: List[str] = []          # int -> external id
        self.doc_index: Dict[str, int] = {}   # external id -> int
        self.doc_len: List[int] = []
        self.doc_tf: List[Counter] = []       # forward index (needed by VSM norms, PRF, clustering)
        self.deleted: set[int] = set()
        # dynamic indexing: small in-memory auxiliary index merged periodically (IIR §4.5)
        self._aux: Dict[str, Postings] = defaultdict(dict)
        self._aux_tokens = 0
        self.aux_merge_threshold = 20_000
        self.blocks_written = 0

    # ------------------------------------------------------------------ build
    def build(self, docs: Iterable[Tuple[str, str]]) -> "InvertedIndex":
        """SPIMI: invert block-by-block, then k-way merge the sorted blocks."""
        blocks: List[List[Tuple[str, Postings]]] = []
        block: Dict[str, Postings] = defaultdict(dict)
        block_tokens = 0
        for ext_id, text in docs:
            did, toks = self._register(ext_id, text)
            for pos, t in enumerate(toks):
                block[t].setdefault(did, []).append(pos)
            block_tokens += len(toks)
            if block_tokens >= self.block_size:
                blocks.append(sorted(block.items()))
                block, block_tokens = defaultdict(dict), 0
        if block:
            blocks.append(sorted(block.items()))
        self.blocks_written = len(blocks)
        self.postings = self._merge_blocks(blocks)
        return self

    @staticmethod
    def _merge_blocks(blocks: List[List[Tuple[str, Postings]]]) -> Dict[str, Postings]:
        merged: Dict[str, Postings] = {}
        for term, plist in heapq.merge(*blocks, key=lambda kv: kv[0]):
            merged.setdefault(term, {}).update(plist)
        return merged

    def _register(self, ext_id: str, text: str) -> Tuple[int, List[str]]:
        if ext_id in self.doc_index:
            raise ValueError(f"duplicate doc id {ext_id}")
        did = len(self.doc_ids)
        toks = self.analyzer(text)
        self.doc_ids.append(ext_id)
        self.doc_index[ext_id] = did
        self.doc_len.append(len(toks))
        self.doc_tf.append(Counter(toks))
        return did, toks

    # ------------------------------------------------------------------ dynamic indexing
    def add_document(self, ext_id: str, text: str) -> int:
        did, toks = self._register(ext_id, text)
        for pos, t in enumerate(toks):
            self._aux[t].setdefault(did, []).append(pos)
        self._aux_tokens += len(toks)
        if self._aux_tokens >= self.aux_merge_threshold:
            self.merge_auxiliary()
        return did

    def merge_auxiliary(self) -> None:
        for t, plist in self._aux.items():
            self.postings.setdefault(t, {}).update(plist)
        self._aux, self._aux_tokens = defaultdict(dict), 0

    def delete_document(self, ext_id: str) -> None:
        """Lazy deletion via invalidation bit-vector (IIR §4.5); purged on compaction."""
        self.deleted.add(self.doc_index[ext_id])

    # ------------------------------------------------------------------ access
    def get_postings(self, term: str) -> Postings:
        main = self.postings.get(term, {})
        aux = self._aux.get(term)
        if aux:
            main = {**main, **aux}
        if self.deleted:
            main = {d: p for d, p in main.items() if d not in self.deleted}
        return main

    def df(self, term: str) -> int:
        return len(self.get_postings(term))

    def idf(self, term: str) -> float:
        df = self.df(term)
        return math.log10(self.N / df) if df else 0.0

    @property
    def N(self) -> int:
        return len(self.doc_ids) - len(self.deleted)

    @property
    def avgdl(self) -> float:
        live = [l for i, l in enumerate(self.doc_len) if i not in self.deleted]
        return sum(live) / max(len(live), 1)

    @property
    def vocabulary(self) -> List[str]:
        return sorted(set(self.postings) | set(self._aux))

    def collection_tf(self) -> Counter:
        c: Counter = Counter()
        for i, tf in enumerate(self.doc_tf):
            if i not in self.deleted:
                c.update(tf)
        return c

    def live_docs(self) -> List[int]:
        return [i for i in range(len(self.doc_ids)) if i not in self.deleted]

    def stats(self) -> IndexStats:
        self.merge_auxiliary()
        return IndexStats(self.N, len(self.postings),
                          sum(len(p) for p in self.postings.values()),
                          sum(self.doc_len), self.avgdl)

    # ------------------------------------------------------------------ phrase / proximity
    def phrase_match(self, terms: List[str], slop: int = 0) -> Dict[int, int]:
        """Positional intersection (IIR §2.4.2). slop=0 -> exact phrase; slop=k -> within k.
        Returns {doc: number_of_matches}."""
        if not terms:
            return {}
        plists = [self.get_postings(t) for t in terms]
        common = set(plists[0])
        for p in plists[1:]:
            common &= set(p)
        hits: Dict[int, int] = {}
        for d in common:
            starts = plists[0][d]
            count = 0
            for s in starts:
                prev, ok = s, True
                for p in plists[1:]:
                    nxt = [x for x in p[d] if prev < x <= prev + 1 + slop]
                    if not nxt:
                        ok = False
                        break
                    prev = nxt[0]
                count += ok
            if count:
                hits[d] = count
        return hits

    # ------------------------------------------------------------------ persistence
    def save(self, path: str | Path) -> None:
        self.merge_auxiliary()
        with open(path, "wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def load(path: str | Path) -> "InvertedIndex":
        with open(path, "rb") as f:
            return pickle.load(f)
