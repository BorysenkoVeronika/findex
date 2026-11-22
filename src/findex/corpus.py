"""Read plain-text documents and crawler JSONL as a lazy corpus."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class Document(NamedTuple):
    doc_id: str
    path: Path
    text: str


def iter_documents(root: Path) -> Iterator[Document]:
    """Stream text files and individual crawled pages without loading the corpus."""
    for path in sorted(root.rglob("*.txt")):
        try:
            yield Document(doc_id=path.stem, path=path, text=path.read_text(encoding="utf-8"))
        except (UnicodeError, OSError) as exc:
            logger.warning("Failed to read file %s: %s", path, exc)

    for path in sorted(root.rglob("*.jsonl")):
        try:
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict) or not isinstance(record.get("text"), str):
                            raise ValueError("Missing string text field")
                        title = record.get("title") or record.get("url") or f"{path.stem}:{line_number}"
                        yield Document(doc_id=str(title), path=path, text=record["text"])
                    except (ValueError, TypeError) as exc:
                        logger.warning("Invalid JSONL record %s:%s: %s", path, line_number, exc)
        except (UnicodeError, OSError) as exc:
            logger.warning("Failed to read file %s: %s", path, exc)
