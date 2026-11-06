import re
import unicodedata
from collections.abc import Iterator

# Tokens contain letters and digits.
# Underscores, hyphens, apostrophes and other punctuation
# act as separators.
WORD_PATTERN = re.compile(r"[^\W_]+")


def tokenize(text: str) -> Iterator[str]:
    text = unicodedata.normalize("NFC", text)
    text = text.casefold()

    for match in WORD_PATTERN.finditer(text):
        yield match.group()