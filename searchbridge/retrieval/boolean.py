"""Boolean retrieval with a small query language (Syllabus Modules 2 & 5).

Grammar (recursive descent, precedence NOT > AND > OR, implicit AND between operands):
    expr    := and_expr ("OR" and_expr)*
    and_expr:= not_expr (["AND"] not_expr)*
    not_expr:= "NOT" not_expr | atom
    atom    := "(" expr ")" | PHRASE["~"k] | WILDCARD | TERM

Examples:
    boundary AND layer AND NOT turbulent
    "heat transfer"~2 OR (shock AND wave*)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Set, Union

from ..index.inverted_index import InvertedIndex

_TOKEN = re.compile(r'"[^"]+"(?:~\d+)?|\(|\)|[^\s()"]+')


@dataclass
class Term:
    text: str

@dataclass
class Phrase:
    words: List[str]
    slop: int = 0

@dataclass
class Wildcard:
    pattern: str

@dataclass
class Not:
    child: "Node"

@dataclass
class And:
    children: List["Node"]

@dataclass
class Or:
    children: List["Node"]

Node = Union[Term, Phrase, Wildcard, Not, And, Or]

BOOLEAN_OPS = {"AND", "OR", "NOT"}


def looks_boolean(query: str) -> bool:
    return any(tok in BOOLEAN_OPS for tok in query.split()) or "(" in query


def repair(query: str) -> str:
    """Best-effort fix of an incomplete query while the user is still typing:
    drop dangling operators, balance parentheses, close an open quote."""
    q = query.strip()
    if q.count('"') % 2:
        q += '"'
    toks = _TOKEN.findall(q)
    out: list = []
    for t in toks:
        if t in ("AND", "OR") and (not out or out[-1] in BOOLEAN_OPS or out[-1] == "("):
            continue
        if t == ")" and out.count("(") <= out.count(")"):
            continue
        out.append(t)
    while out and (out[-1] in BOOLEAN_OPS or out[-1] == "("):
        out.pop()
    out += [")"] * (out.count("(") - out.count(")"))
    return " ".join(out)


class BooleanParser:
    def parse(self, query: str) -> Node:
        self.toks = _TOKEN.findall(query)
        self.i = 0
        node = self._expr()
        if self.i != len(self.toks):
            raise ValueError(f"Unexpected token {self.toks[self.i]!r}")
        return node

    def _peek(self) -> Optional[str]:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _expr(self) -> Node:
        kids = [self._and()]
        while self._peek() == "OR":
            self.i += 1
            kids.append(self._and())
        return kids[0] if len(kids) == 1 else Or(kids)

    def _and(self) -> Node:
        kids = [self._not()]
        while self._peek() not in (None, "OR", ")"):
            if self._peek() == "AND":
                self.i += 1
            kids.append(self._not())
        return kids[0] if len(kids) == 1 else And(kids)

    def _not(self) -> Node:
        if self._peek() == "NOT":
            self.i += 1
            return Not(self._not())
        return self._atom()

    def _atom(self) -> Node:
        tok = self._peek()
        if tok is None:
            raise ValueError("Unexpected end of query")
        self.i += 1
        if tok == "(":
            node = self._expr()
            if self._peek() != ")":
                raise ValueError("Missing ')'")
            self.i += 1
            return node
        if tok.startswith('"'):
            m = re.match(r'"([^"]+)"(?:~(\d+))?', tok)
            return Phrase(m.group(1).split(), int(m.group(2) or 0))
        if "*" in tok or "?" in tok:
            return Wildcard(tok.lower())
        return Term(tok)


class BooleanRetriever:
    name = "Boolean"

    def __init__(self, index: InvertedIndex, wildcard_expander: Optional[Callable[[str], List[str]]] = None):
        self.index = index
        self.expand_wildcard = wildcard_expander
        self.parser = BooleanParser()

    def evaluate(self, node: Node) -> Set[int]:
        ix, an = self.index, self.index.analyzer
        if isinstance(node, Term):
            t = an.analyze_term(node.text)
            return set(ix.get_postings(t)) if t else set()
        if isinstance(node, Phrase):
            terms = [t for w in node.words for t in an(w)]
            return set(ix.phrase_match(terms, node.slop))
        if isinstance(node, Wildcard):
            surface = self.expand_wildcard(node.pattern) if self.expand_wildcard else []
            out: Set[int] = set()
            for w in surface:
                out |= set(ix.get_postings(an.analyze_term(w)))
            return out
        if isinstance(node, Not):
            return set(ix.live_docs()) - self.evaluate(node.child)
        if isinstance(node, And):
            # Process positive operands in increasing df order (IIR §1.3 query optimisation).
            pos = [c for c in node.children if not isinstance(c, Not)]
            neg = [c for c in node.children if isinstance(c, Not)]
            sets = sorted((self.evaluate(c) for c in pos), key=len)
            res = sets[0] if sets else set(ix.live_docs())
            for s in sets[1:]:
                res = res & s
                if not res:
                    break
            for c in neg:
                res = res - self.evaluate(c.child)
            return res
        if isinstance(node, Or):
            res: Set[int] = set()
            for c in node.children:
                res |= self.evaluate(c)
            return res
        raise TypeError(node)

    def search_query(self, query: str) -> Set[int]:
        return self.evaluate(self.parser.parse(query))
