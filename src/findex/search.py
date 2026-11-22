"""Boolean merging, ranked search, snippets and swappable scorers."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import heapq
import math
import re
from typing import Protocol

from findex.index import Index, Posting
from findex.query import parse


def merge_and(left: list[int], right: list[int]) -> list[int]:
    output: list[int] = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            output.append(left[i]); i += 1; j += 1
        elif left[i] < right[j]:
            i += 1
        else:
            j += 1
    return output


def merge_or(left: list[int], right: list[int]) -> list[int]:
    output: list[int] = []
    i = j = 0
    while i < len(left) or j < len(right):
        if j == len(right) or (i < len(left) and left[i] < right[j]):
            candidate = left[i]; i += 1
        elif i == len(left) or right[j] < left[i]:
            candidate = right[j]; j += 1
        else:
            candidate = left[i]; i += 1; j += 1
        if not output or output[-1] != candidate:
            output.append(candidate)
    return output


def boolean_search(index: Index, query: str, *, engine: str = 'merge') -> list[int]:
    if engine not in ('merge', 'set'):
        raise ValueError('engine must be merge or set')
    from findex.query import And, Or, Not, Term, Phrase
    node = parse(query)
    if engine == 'set':
        return sorted(node.evaluate(index))

    def evaluate(n):
        if isinstance(n, Term):
            return [p.doc_id for p in index.postings.get(n.value, ())]
        if isinstance(n, Phrase):
            return sorted(n.evaluate(index))
        if isinstance(n, And):
            return merge_and(evaluate(n.left), evaluate(n.right))
        if isinstance(n, Or):
            return merge_or(evaluate(n.left), evaluate(n.right))
        if isinstance(n, Not):
            return sorted(set(index.doc_meta) - set(evaluate(n.child)))
        raise TypeError('Unsupported query node')

    return evaluate(node)


class Scorer(Protocol):
    def score(self, term: str, posting: Posting, index: Index) -> float: ...


@dataclass(frozen=True)
class TfIdf:
    def score(self, term: str, posting: Posting, index: Index) -> float:
        return (1 + math.log(posting.tf)) * (math.log((index.num_docs + 1) / (index.df(term) + 1)) + 1)

    def __call__(self, term: str, posting: Posting, index: Index) -> float:
        return self.score(term, posting, index)


@dataclass(frozen=True)
class BM25:
    k1: float = 1.5
    b: float = 0.75

    def score(self, term: str, posting: Posting, index: Index) -> float:
        idf = math.log(1 + (index.num_docs - index.df(term) + .5) / (index.df(term) + .5))
        norm = posting.tf + self.k1 * (1 - self.b + self.b * index.doc_length(posting.doc_id) / (index.avg_doc_length or 1))
        return idf * posting.tf * (self.k1 + 1) / norm

    def __call__(self, term: str, posting: Posting, index: Index) -> float:
        return self.score(term, posting, index)


@dataclass(order=True, frozen=True)
class SearchResult:
    score: float
    doc_id: int = field(compare=False)
    title: str = field(compare=False)
    snippet: str = field(default='', compare=False)

    def __str__(self) -> str:
        return f'{self.score:.4f}  {self.title}  {self.snippet}'


def make_snippet(text: str, terms: set[str], radius: int = 80) -> str:
    if not text:
        return ''
    lowered = text.casefold()
    offsets = [lowered.find(t) for t in terms if t and t in lowered]
    start = max(0, min(offsets) - radius) if offsets else 0
    end = min(len(text), start + radius * 2)
    extract = text[start:end].replace('\n', ' ')
    if terms:
        pattern = re.compile('(' + '|'.join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + ')', re.I)
        extract = pattern.sub(r'**\1**', extract)
    return ('…' if start else '') + extract + ('…' if end < len(text) else '')


# Index instances are mutable and unhashable: cache the compiled query itself.
@lru_cache(maxsize=256)
def _parse_cached(query: str):
    return parse(query)


def search(index: Index, query: str, *, scorer: Scorer | None = None, k: int = 10) -> list[SearchResult]:
    if k < 1:
        return []
    node = _parse_cached(query)
    matches = node.evaluate(index)
    terms = node.terms()
    scorer = scorer or BM25()
    scores: dict[int, float] = {doc_id: 0.0 for doc_id in matches}
    for term in terms:
        for post in index.postings.get(term, ()):
            if post.doc_id in matches:
                scores[post.doc_id] += scorer.score(term, post, index)
    ids = heapq.nlargest(k, scores, key=lambda d: (scores[d], -d))
    return [SearchResult(scores[d], d, index.doc_meta[d].title, make_snippet(index.doc_meta[d].text, terms)) for d in ids]


def main() -> None:
    import argparse
    import time
    import tracemalloc
    from pathlib import Path
    from findex.store import load
    parser = argparse.ArgumentParser()
    parser.add_argument('index', type=Path)
    parser.add_argument('query')
    parser.add_argument('--engine', choices=['merge', 'set'], default='merge')
    args = parser.parse_args()
    tracemalloc.start(); start = time.perf_counter()
    index = load(args.index)
    for result in search(index, args.query):
        print(result)
    _, peak = tracemalloc.get_traced_memory()
    print(f'Elapsed: {time.perf_counter()-start:.4f}s; peak: {peak} bytes')


if __name__ == '__main__':
    main()
