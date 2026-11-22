"""Build and merge partial indexes using serial, thread or process executors."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from findex.corpus import Document, logger
from findex.index import Index, Posting, build_from_documents, build_index


@dataclass(frozen=True)
class PartialIndex:
    index: Index


def build_partial(doc_paths: list[tuple[int, Path]], positions: bool = True) -> PartialIndex:
    """Index file paths using provisional IDs assigned before dispatch."""
    index = Index()

    for doc_id, path in doc_paths:
        try:
            document = Document(path.stem, path, path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as error:
            logger.warning("Failed to read file %s: %s", path, error)
            continue

        partial = build_from_documents([document], positions=positions, start_id=doc_id)
        index.doc_meta.update(partial.doc_meta)
        index.doc_lengths.update(partial.doc_lengths)

        for term, postings in partial.postings.items():
            index.postings.setdefault(term, []).extend(postings)

    return PartialIndex(index)


def merge(partials: Iterable[PartialIndex]) -> Index:
    """Merge chunks and compact IDs so skipped files leave no gaps."""
    combined = Index()

    for partial in partials:
        combined.doc_meta.update(partial.index.doc_meta)
        combined.doc_lengths.update(partial.index.doc_lengths)
        for term, postings in partial.index.postings.items():
            combined.postings.setdefault(term, []).extend(postings)

    # Sequential indexing assigns IDs only to successfully decoded documents.
    # Map provisional path IDs onto that same compact, ascending sequence.
    id_map = {old_id: new_id for new_id, old_id in enumerate(sorted(combined.doc_meta))}
    result = Index()
    result.doc_meta = {id_map[old_id]: metadata for old_id, metadata in combined.doc_meta.items()}
    result.doc_lengths = {id_map[old_id]: length for old_id, length in combined.doc_lengths.items()}

    for term, postings in combined.postings.items():
        result.postings[term] = sorted(
            (Posting(id_map[p.doc_id], p.tf, p.positions) for p in postings),
            key=lambda p: p.doc_id,
        )

    return result


def build_parallel(
    root: Path,
    *,
    workers: int = 1,
    executor: str = "serial",
    positions: bool = True,
    limit: int | None = None,
) -> Index:
    """Distribute sorted file paths, not preloaded documents, to workers."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if executor not in ("serial", "threads", "processes"):
        raise ValueError(f"Unknown executor: {executor}")

    # JSONL records contain multiple documents per path; use the streaming
    # reader so every record is indexed once with stable document IDs.
    if any(root.rglob("*.jsonl")):
        return build_index(root, positions=positions, limit=limit)

    paths = sorted(root.rglob("*.txt"))
    # Like islice(iter_documents(root), limit), limit counts valid documents.
    # To preserve that behavior without pre-reading data, apply the limit
    # only after the merged index has been compacted.
    indexed = list(enumerate(paths))
    if not indexed or limit == 0:
        return Index()

    worker_count = min(workers, len(indexed))
    chunks = [indexed[i::worker_count] for i in range(worker_count)]

    if executor == "serial":
        partials = [build_partial(chunk, positions) for chunk in chunks]
    else:
        pool = ThreadPoolExecutor if executor == "threads" else ProcessPoolExecutor
        with pool(max_workers=worker_count) as pool_executor:
            partials = list(
                pool_executor.map(
                    build_partial,
                    chunks,
                    [positions] * len(chunks),
                )
            )

    result = merge(partials)
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be nonnegative")
        keep = set(range(limit))
        result.doc_meta = {k: v for k, v in result.doc_meta.items() if k in keep}
        result.doc_lengths = {k: v for k, v in result.doc_lengths.items() if k in keep}
        result.postings = {
            term: filtered
            for term, postings in result.postings.items()
            if (filtered := [p for p in postings if p.doc_id in keep])
        }
    return result
