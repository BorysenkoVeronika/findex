"""Boolean query AST with implicit AND, explicit OR/NOT and phrases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from findex.index import Index
from findex.tokenize import tokenize


class QueryNode:
    def evaluate(self, index: Index) -> set[int]:
        raise NotImplementedError

    def __and__(self, other: QueryNode) -> QueryNode:
        return And(self, other)

    def __or__(self, other: QueryNode) -> QueryNode:
        return Or(self, other)

    def __invert__(self) -> QueryNode:
        return Not(self)

    def terms(self) -> set[str]:
        raise NotImplementedError


@dataclass(frozen=True)
class Term(QueryNode):
    value: str

    def evaluate(self, index: Index) -> set[int]:
        return {p.doc_id for p in index.postings.get(self.value, ())}

    def terms(self) -> set[str]:
        return {self.value}


@dataclass(frozen=True)
class Phrase(QueryNode):
    value: tuple[str, ...]

    def evaluate(self, index: Index) -> set[int]:
        if not self.value:
            return set()
        candidates = [dict((p.doc_id, p.positions) for p in index.postings.get(t, ())) for t in self.value]
        docs = set(candidates[0]).intersection(*(set(c) for c in candidates[1:]))
        return {
            doc
            for doc in docs
            if any(
                all(start + i in candidates[i][doc] for i in range(1, len(candidates))) for start in candidates[0][doc]
            )
        }

    def terms(self) -> set[str]:
        return set(self.value)


@dataclass(frozen=True)
class And(QueryNode):
    left: QueryNode
    right: QueryNode

    def evaluate(self, index: Index) -> set[int]:
        return self.left.evaluate(index) & self.right.evaluate(index)

    def terms(self) -> set[str]:
        return self.left.terms() | self.right.terms()


@dataclass(frozen=True)
class Or(QueryNode):
    left: QueryNode
    right: QueryNode

    def evaluate(self, index: Index) -> set[int]:
        return self.left.evaluate(index) | self.right.evaluate(index)

    def terms(self) -> set[str]:
        return self.left.terms() | self.right.terms()


@dataclass(frozen=True)
class Not(QueryNode):
    child: QueryNode

    def evaluate(self, index: Index) -> set[int]:
        return set(index.doc_meta) - self.child.evaluate(index)

    def terms(self) -> set[str]:
        return set()


_TOKEN_RE = re.compile(r'"[^"]*"|\(|\)|\b(?:AND|OR|NOT)\b|[^\s()]+', re.IGNORECASE)


def parse(query: str) -> QueryNode:
    tokens = _TOKEN_RE.findall(query)
    if not tokens:
        raise ValueError("Query must not be empty")
    pos = 0

    def atom() -> QueryNode:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Unexpected end of query")
        token = tokens[pos]
        pos += 1
        if token.upper() == "NOT":
            return Not(atom())
        if token == "(":
            node = disjunction()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise ValueError("Missing closing parenthesis")
            pos += 1
            return node
        if token == ")" or token.upper() in ("AND", "OR"):
            raise ValueError(f"Unexpected token: {token}")
        if token.startswith('"'):
            terms = tuple(tokenize(token[1:-1]))
            if not terms:
                raise ValueError("Empty phrase")
            return Phrase(terms)
        words = list(tokenize(token))
        if not words:
            raise ValueError("Invalid term")
        node: QueryNode = Term(words[0])
        for word in words[1:]:
            node = And(node, Term(word))
        return node

    def conjunction() -> QueryNode:
        nonlocal pos
        node = atom()
        while pos < len(tokens) and tokens[pos] != ")" and tokens[pos].upper() != "OR":
            if tokens[pos].upper() == "AND":
                pos += 1
            node = And(node, atom())
        return node

    def disjunction() -> QueryNode:
        nonlocal pos
        node = conjunction()
        while pos < len(tokens) and tokens[pos].upper() == "OR":
            pos += 1
            node = Or(node, conjunction())
        return node

    result = disjunction()
    if pos != len(tokens):
        raise ValueError(f"Unexpected token: {tokens[pos]}")
    return result
