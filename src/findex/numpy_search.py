"""Vectorized scoring and compact on-disk postings for Findex."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from findex.index import Index
from findex.search import BM25, TfIdf, SearchResult, make_snippet
from findex.query import parse


@dataclass(frozen=True)
class PostingArrays:
    doc_ids: NDArray[np.int32]
    tfs: NDArray[np.int32]


def as_arrays(index: Index) -> dict[str, PostingArrays]:
    """Build dense numeric postings with no Python objects in scorer hot loops."""
    arrays: dict[str, PostingArrays] = {}
    for term, postings in index.postings.items():
        pairs = np.fromiter((v for p in postings for v in (p.doc_id, p.tf)), dtype=np.int32)
        values = pairs.reshape(-1, 2)
        arrays[term] = PostingArrays(values[:, 0], values[:, 1])
    return arrays


def search_numpy(
    index: Index,
    query: str,
    *,
    scorer: BM25 | TfIdf | None = None,
    k: int = 10,
    arrays: dict[str, PostingArrays] | None = None,
) -> list[SearchResult]:
    """Rank with NumPy, preserving the classic scorer's tie-breaking rule."""
    if k <= 0:
        return []
    node = parse(query)
    matches = node.evaluate(index)
    if not matches:
        return []
    terms = node.terms()
    chosen = scorer if scorer is not None else BM25()
    posting_arrays = arrays if arrays is not None else as_arrays(index)
    # Document IDs are stable, but need not be contiguous in externally built indices.
    ids_all = sorted(index.doc_meta)
    if not ids_all:
        return []
    max_id = ids_all[-1]
    lengths = np.zeros(max_id + 1, dtype=np.int32)
    for doc_id, length in index.doc_lengths.items():
        lengths[doc_id] = length
    scores = np.zeros(max_id + 1, dtype=np.float64)
    n_docs = index.num_docs
    for term in terms:
        posts = posting_arrays.get(term)
        if posts is None or not len(posts.doc_ids):
            continue
        doc_ids = posts.doc_ids
        tfs = posts.tfs.astype(np.float64)
        df = len(doc_ids)
        if isinstance(chosen, BM25):
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            denominator = tfs + chosen.k1 * (1 - chosen.b + chosen.b * lengths[doc_ids] / (index.avg_doc_length or 1))
            contributions = idf * tfs * (chosen.k1 + 1) / denominator
        else:
            idf = math.log((n_docs + 1) / (df + 1)) + 1
            contributions = (1 + np.log(tfs)) * idf
        np.add.at(scores, doc_ids, contributions)
    eligible = np.fromiter(sorted(matches), dtype=np.int32)
    # argpartition reduces candidate selection to O(n), then stable ordering
    # reproduces heapq.nlargest(..., key=(score, -doc_id)).
    limit = min(k, len(eligible))
    if limit < len(eligible):
        boundary = np.partition(scores[eligible], -limit)[-limit]
        above = eligible[scores[eligible] > boundary]
        equal = eligible[scores[eligible] == boundary]
        selected = np.concatenate((above, equal[: max(0, limit - len(above))]))
    else:
        selected = eligible
    ordered = sorted((int(d) for d in selected), key=lambda d: (-float(scores[d]), d))[:limit]
    return [
        SearchResult(float(scores[d]), d, index.doc_meta[d].title, make_snippet(index.doc_meta[d].text, terms))
        for d in ordered
    ]


def save_compressed(index: Index, directory: Path) -> None:
    """Gap-encode doc IDs and save a memory-mappable int32 postings stream."""
    directory.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, list[int]] = {}
    chunks: list[NDArray[np.int32]] = []
    offset = 0
    for term, postings in sorted(index.postings.items()):
        ids = np.fromiter((p.doc_id for p in postings), dtype=np.int32)
        tfs = np.fromiter((p.tf for p in postings), dtype=np.int32)
        gaps = np.diff(ids, prepend=np.int32(0))
        pairs = np.column_stack((gaps, tfs)).ravel().astype(np.int32)
        metadata[term] = [offset, len(ids)]
        chunks.append(pairs)
        offset += len(pairs)
    buffer = np.concatenate(chunks) if chunks else np.empty(0, dtype=np.int32)
    buffer.tofile(directory / "postings.i32")
    (directory / "terms.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")


def load_compressed(directory: Path) -> dict[str, PostingArrays]:
    """Read the compact postings file lazily via mmap, decoding gaps per term."""
    metadata: dict[str, list[int]] = json.loads((directory / "terms.json").read_text(encoding="utf-8"))
    file = directory / "postings.i32"
    raw: NDArray[np.int32] = (
        np.memmap(file, dtype=np.int32, mode="r") if file.stat().st_size else np.empty(0, dtype=np.int32)
    )
    postings: dict[str, PostingArrays] = {}
    for term, (offset, n) in metadata.items():
        values = raw[offset : offset + 2 * n].reshape(-1, 2)
        postings[term] = PostingArrays(np.cumsum(values[:, 0], dtype=np.int32), values[:, 1])
    return postings
