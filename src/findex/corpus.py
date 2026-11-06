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

    for file in root.rglob("*.txt"):
        try:
            text = file.read_text(encoding="utf-8")

            yield Document(
                doc_id=file.stem,
                path=file,
                text=text,
            )

        except (UnicodeDecodeError, OSError) as error:
            logger.warning(
                "Failed to read file %s: %s",
                file,
                error,
            )
            continue