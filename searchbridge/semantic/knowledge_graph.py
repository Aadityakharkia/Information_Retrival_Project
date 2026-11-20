"""Corpus knowledge graph (Syllabus Module 8: Knowledge Graphs in IR).

Nodes : ontology concepts + mined key-phrases ("entities")
Edges : (a) ontology relations (broader / related), (b) document co-occurrence weighted by
        NPMI, (c) entity -> document "mentions" links.
Uses  : entity-aware query expansion, "related concepts" panel, and entity-overlap signal
        for related-document ("bridge") discovery.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..text.preprocess import tokenize
from .entities import CollocationMiner, Ontology


class KnowledgeGraph:
    def __init__(self, ontology: Optional[Ontology] = None, miner: Optional[CollocationMiner] = None):
        self.ontology = ontology
        self.miner = miner
        self.doc_entities: List[Set[str]] = []
        self.entity_docs: Dict[str, Set[int]] = defaultdict(set)
        self.edges: Dict[str, Dict[str, float]] = defaultdict(dict)

    def _entities(self, text: str) -> Set[str]:
        ents: Set[str] = set()
        if self.ontology:
            ents |= {f"concept:{m.concept}" for m in self.ontology.link(text)}
        if self.miner:
            ents |= set(self.miner.extract(text))
        return ents

    def build(self, texts: Sequence[str], min_cooc: int = 3,
              doc_tags: Optional[Sequence[Sequence[str]]] = None) -> "KnowledgeGraph":
        """doc_tags: optional author keyphrases per document, used as (high-precision) entities."""
        cooc: Counter = Counter()
        tag_df: Counter = Counter()
        if doc_tags:
            for tags in doc_tags:
                tag_df.update({t.lower() for t in tags})
        # tags shared by >= 2 documents become a gazetteer for recognising entities in queries
        self.tag_vocab = {t for t, c in tag_df.items() if c >= 2 and len(t) > 2}
        for i, t in enumerate(texts):
            ents = self._entities(t)
            if doc_tags:
                ents |= {x.lower() for x in doc_tags[i] if x.lower() in self.tag_vocab}
            self.doc_entities.append(ents)
            for e in ents:
                self.entity_docs[e].add(i)
            es = sorted(ents)
            for a in range(len(es)):
                for b in range(a + 1, len(es)):
                    cooc[(es[a], es[b])] += 1
        N = len(texts)
        for (a, b), c in cooc.items():
            if c < min_cooc:
                continue
            pa, pb, pab = len(self.entity_docs[a]) / N, len(self.entity_docs[b]) / N, c / N
            npmi = math.log(pab / (pa * pb)) / -math.log(pab) if pab < 1 else 1.0
            if npmi > 0:
                self.edges[a][b] = self.edges[b][a] = npmi
        if self.ontology:  # ontology relations as strong typed edges
            for c in self.ontology.concepts.values():
                for r in c.broader + c.related:
                    self.edges[f"concept:{c.cid}"][f"concept:{r}"] = max(self.edges[f"concept:{c.cid}"].get(f"concept:{r}", 0), 0.8)
                    self.edges[f"concept:{r}"][f"concept:{c.cid}"] = max(self.edges[f"concept:{r}"].get(f"concept:{c.cid}", 0), 0.8)
        return self

    def label(self, node: str) -> str:
        if node.startswith("concept:") and self.ontology:
            c = self.ontology.concepts.get(node[8:])
            return c.label if c else node
        return node

    def neighbours(self, node: str, k: int = 8) -> List[Tuple[str, float]]:
        return sorted(self.edges.get(node, {}).items(), key=lambda x: -x[1])[:k]

    def query_entities(self, text: str) -> Set[str]:
        ents = self._entities(text)
        low = " " + " ".join(tokenize(text)) + " "
        ents |= {t for t in getattr(self, "tag_vocab", ()) if f" {' '.join(tokenize(t))} " in low}
        return ents

    def subgraph(self, seeds: Optional[Set[str]] = None, max_nodes: int = 40) -> Dict[str, list]:
        """Nodes/edges for visualisation: seeds + strongest neighbours, or the global hubs."""
        if seeds:
            nodes = [s for s in seeds if s in self.edges or s in self.entity_docs]
            for s in list(nodes):
                for n, _ in self.neighbours(s, 8):
                    if n not in nodes:
                        nodes.append(n)
            for s in list(nodes[len(seeds):]):
                if len(nodes) >= max_nodes:
                    break
                for n, _ in self.neighbours(s, 3):
                    if n not in nodes and len(nodes) < max_nodes:
                        nodes.append(n)
        else:
            hubs = sorted(self.edges, key=lambda n: -(len(self.edges[n]) * len(self.entity_docs.get(n, ()))))
            nodes = hubs[:max_nodes]
        # merge nodes that display the same label (e.g. a keyphrase and the ontology concept)
        seen_labels, uniq = {}, []
        from ..text.preprocess import stem
        for n in nodes:
            lab = " ".join(stem(w) for w in tokenize(self.label(n)))
            if lab not in seen_labels:
                seen_labels[lab] = n
                uniq.append(n)
        nodes = uniq[:max_nodes]
        ns = set(nodes)
        connected = {a for a in nodes for b in self.edges.get(a, {}) if b in ns}
        if connected:   # drop isolated nodes (e.g. single words of a multi-word query)
            nodes = [n for n in nodes if n in connected]
            ns = set(nodes)
        edges = [(a, b, round(w, 3)) for a in nodes for b, w in self.edges.get(a, {}).items() if b in ns and a < b]
        return {"nodes": [{"id": n, "label": self.label(n), "docs": len(self.entity_docs.get(n, ())),
                           "seed": bool(seeds and n in seeds), "concept": n.startswith("concept:")} for n in nodes],
                "edges": [{"source": a, "target": b, "weight": w} for a, b, w in edges]}

    def expansion_terms(self, text: str, k: int = 6) -> List[Tuple[str, float]]:
        """Surface phrases of KG neighbours of the query's entities."""
        scores: Dict[str, float] = defaultdict(float)
        q_ents = self.query_entities(text)
        for e in q_ents:
            for n, w in self.neighbours(e, k):
                if n not in q_ents:
                    scores[self.label(n)] += w
        return sorted(scores.items(), key=lambda x: -x[1])[:k]

    def entity_overlap(self, d1: int, d2: int) -> float:
        a, b = self.doc_entities[d1], self.doc_entities[d2]
        return len(a & b) / len(a | b) if a | b else 0.0

    def to_edge_list(self, max_edges: int = 300) -> List[Tuple[str, str, float]]:
        seen, out = set(), []
        for a, nb in self.edges.items():
            for b, w in nb.items():
                if (b, a) not in seen:
                    seen.add((a, b))
                    out.append((self.label(a), self.label(b), w))
        return sorted(out, key=lambda x: -x[2])[:max_edges]
