"""Boolean search over a sorted inverted index (Lab 02)."""
from __future__ import annotations
import argparse
from pathlib import Path
from time import perf_counter
import tracemalloc
from findex.index import Index


def merge_and(left: list[int], right: list[int]) -> list[int]:
    result: list[int] = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            result.append(left[i]); i += 1; j += 1
        elif left[i] < right[j]:
            i += 1
        else:
            j += 1
    return result


def merge_or(left: list[int], right: list[int]) -> list[int]:
    result: list[int] = []
    i = j = 0
    while i < len(left) or j < len(right):
        if j == len(right) or (i < len(left) and left[i] < right[j]):
            value = left[i]; i += 1
        elif i == len(left) or right[j] < left[i]:
            value = right[j]; j += 1
        else:
            value = left[i]; i += 1; j += 1
        if not result or result[-1] != value:
            result.append(value)
    return result


def boolean_search(index: Index, query: str, *, engine: str = 'merge') -> list[int]:
    if engine not in ('merge','set'):
        raise ValueError('engine must be merge or set')
    words = query.casefold().split()
    all_docs = sorted(index.doc_meta)
    def docs(word: str) -> list[int]:
        return [p.doc_id for p in index.postings.get(word, ())]
    if not words:
        return []
    result: list[int] = []
    mode = 'OR'
    negate = False
    for word in words:
        if word in ('or','OR'):
            mode = 'OR'; continue
        if word in ('not','NOT'):
            negate = True; continue
        found = docs(word)
        if negate:
            found = sorted(set(all_docs) - set(found)); negate = False
        if engine == 'set':
            result = sorted((set(result) | set(found)) if mode == 'OR' else (set(result) & set(found)))
        else:
            result = merge_or(result, found) if mode == 'OR' else merge_and(result, found)
        mode = 'AND'
    return result


def main() -> None:
    from findex.store import load
    parser = argparse.ArgumentParser()
    parser.add_argument('index',type=Path)
    parser.add_argument('query')
    parser.add_argument('--engine',choices=('merge','set'),default='merge')
    args = parser.parse_args()
    tracemalloc.start(); start = perf_counter()
    index = load(args.index)
    for doc_id in boolean_search(index,args.query,engine=args.engine):
        print(index.doc_meta[doc_id].title)
    _,peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    print(f'Elapsed: {perf_counter()-start:.4f}s; peak: {peak} bytes')

if __name__ == '__main__':
    main()
