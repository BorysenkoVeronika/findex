"""Streaming inverted index and Python mapping interface."""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from itertools import islice
from pathlib import Path

from findex.corpus import Document, iter_documents
from findex.tokenize import tokenize


@dataclass(frozen=True, slots=True)
class Posting:
    doc_id: int
    tf: int
    positions: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class DocMeta:
    path: str
    title: str
    text: str = ""


@dataclass
class Index(Mapping[str, list[Posting]]):
    postings: dict[str, list[Posting]] = field(default_factory=dict)
    doc_lengths: dict[int, int] = field(default_factory=dict)
    doc_meta: dict[int, DocMeta] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.postings)

    def __iter__(self) -> Iterator[str]:
        return iter(self.postings)

    def __getitem__(self, term: str) -> list[Posting]:
        return self.postings[term]

    def __contains__(self, term: object) -> bool:
        return term in self.postings

    def __repr__(self) -> str:
        return f"Index(terms={len(self):_}, docs={self.num_docs:_})"

    @property
    def num_docs(self) -> int:
        return len(self.doc_meta)

    @cached_property
    def avg_doc_length(self) -> float:
        return sum(self.doc_lengths.values()) / self.num_docs if self.num_docs else 0.0

    def doc_length(self, doc_id: int) -> int:
        return self.doc_lengths[doc_id]

    def df(self, term: str) -> int:
        return len(self.postings.get(term, ()))

    def __getstate__(self) -> dict[str, object]:
        return {"postings": self.postings, "doc_lengths": self.doc_lengths, "doc_meta": self.doc_meta}

    def __setstate__(self, state: dict[str, object]) -> None:
        self.__dict__.update(state)


def build_from_documents(documents: Iterable[Document], *, positions: bool = True, start_id: int = 0) -> Index:
    index = Index()
    for doc_id, doc in enumerate(documents, start_id):
        tokens = list(tokenize(doc.text))
        index.doc_lengths[doc_id] = len(tokens)
        index.doc_meta[doc_id] = DocMeta(str(doc.path), doc.doc_id, doc.text)
        occurrences: dict[str, list[int]] = defaultdict(list)
        for pos, term in enumerate(tokens):
            occurrences[term].append(pos)
        for term, offsets in occurrences.items():
            index.postings.setdefault(term, []).append(
                Posting(doc_id, len(offsets), tuple(offsets) if positions else ())
            )
    return index


def build_index(root: Path, *, positions: bool = True, limit: int | None = None) -> Index:
    return build_from_documents(islice(iter_documents(root), limit), positions=positions)


def main() -> None:
    import argparse
    from findex.store import save
    from time import perf_counter
    import tracemalloc
    parser = argparse.ArgumentParser()
    parser.add_argument('corpus', type=Path)
    parser.add_argument('--out', type=Path, default=Path('index.bin'))
    parser.add_argument('--positions', action='store_true')
    args = parser.parse_args()
    tracemalloc.start()
    start = perf_counter()
    # Use the importable module so pickle records findex.index, not __main__.
    from findex.index import build_index as canonical_build_index
    ix = canonical_build_index(args.corpus, positions=args.positions)
    save(ix, args.out)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f'{ix!r} built in {perf_counter()-start:.4f}s; peak {peak} bytes')


if __name__ == '__main__':
    main()
