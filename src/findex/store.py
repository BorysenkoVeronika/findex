"""Index persistence. Never unpickle a file from an untrusted source."""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import pickle
from collections.abc import Generator

from findex.index import DocMeta, Index, Posting

logger = logging.getLogger(__name__)


def save(index: Index, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        obj = {
            "postings": {
                term: [[p.doc_id, p.tf, list(p.positions)] for p in posts] for term, posts in index.postings.items()
            },
            "doc_lengths": index.doc_lengths,
            "doc_meta": {str(k): {"path": v.path, "title": v.title, "text": v.text} for k, v in index.doc_meta.items()},
        }
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    else:
        with path.open("wb") as stream:
            pickle.dump(index, stream, protocol=pickle.HIGHEST_PROTOCOL)


def load(path: Path) -> Index:
    if path.suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        return Index(
            {t: [Posting(int(d), int(tf), tuple(pos)) for d, tf, pos in posts] for t, posts in obj["postings"].items()},
            {int(k): int(v) for k, v in obj["doc_lengths"].items()},
            {int(k): DocMeta(**v) for k, v in obj["doc_meta"].items()},
        )
    # SECURITY: pickle can execute arbitrary code during deserialization.
    # Only load files you created yourself and fully trust.
    with path.open("rb") as stream:
        value = pickle.load(stream)  # noqa: S301
    if not isinstance(value, Index):
        raise ValueError("Not a findex index")
    return value


@contextmanager
def open_index(path: Path) -> Generator[Index]:
    index = load(path)
    try:
        yield index
    finally:
        del index
