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
    """Only upper-case AND / OR / NOT make a query Boolean; parentheses alone are ordinary punctuation
    in natural-language queries ("kinetic theory (chapman-enskog)")."""
    return any(tok.strip("()") in BOOLEAN_OPS for tok in query.split())


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
        tok = tok.rstrip("?") or tok           # trailing '?' ends a question; inside a word it is a wildcard
        if "*" in tok or "?" in tok:
            return Wildcard(tok.lower())
        return Term(tok)


class BooleanRetriever:
    name = "Boolean"

    def __init__(self, index: InvertedIndex, wildcard_expander: Optional[Callable[[str], List[str]]] = None):
        self.index = index
        self.expand_wildcard = wildcard_expander
        self.parser = BooleanParser()

    def evaluate(self, node: Node) -> Optional[Set[int]]:
        """Matching documents, or None for an operand that carries no terms (a stop word such as "the",
        or a lower-case "and"): such operands are ignored, exactly as they are at indexing time,
        instead of emptying the whole AND."""
        ix, an = self.index, self.index.analyzer
        if isinstance(node, Term):
            t = an.analyze_term(node.text)
            return set(ix.get_postings(t)) if t else None
        if isinstance(node, Phrase):
            terms = [t for w in node.words for t in an(w)]
            return set(ix.phrase_match(terms, node.slop)) if terms else None
        if isinstance(node, Wildcard):
            surface = self.expand_wildcard(node.pattern) if self.expand_wildcard else []
            out: Set[int] = set()
            for w in surface:
                t = an.analyze_term(w)
                if t:
                    out |= set(ix.get_postings(t))
            return out
        if isinstance(node, Not):
            child = self.evaluate(node.child)
            return None if child is None else set(ix.live_docs()) - child
        if isinstance(node, And):
            # Process positive operands in increasing df order (IIR §1.3 query optimisation).
            pos = [s for s in (self.evaluate(c) for c in node.children if not isinstance(c, Not)) if s is not None]
            neg = [s for s in (self.evaluate(c.child) for c in node.children if isinstance(c, Not)) if s is not None]
            if not pos and not neg:
                return None
            sets = sorted(pos, key=len)
            res = set(sets[0]) if sets else set(ix.live_docs())
            for s in sets[1:]:
                res &= s
                if not res:
                    break
            for s in neg:
                res -= s
            return res
        if isinstance(node, Or):
            kids = [s for s in (self.evaluate(c) for c in node.children) if s is not None]
            if not kids:
                return None
            return set().union(*kids)
        raise TypeError(node)

    def search_query(self, query: str) -> Set[int]:
        return self.evaluate(self.parser.parse(query)) or set()
