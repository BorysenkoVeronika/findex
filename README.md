# Findex

A Python project for text corpus processing using iterators, generators, and tokenization.

## Usage

py -m findex.stats data/
py -m findex.stats data/ --limit 1

## Corpus

The corpus consists of sample text files stored in `data/`. The files are local and are not committed to Git.

## Tokenization

- Unicode text is normalized using NFC.
- Text is case-folded for case-insensitive matching.
- Letters and digits are included in tokens.
- Hyphens, apostrophes, and underscores act as separators.

## Eager vs. Lazy

| Version | Documents | Peak Memory | Time |
|---|---:|---:|---:|
| Eager | 3 | 139,695 bytes | 0.00178 s |
| Lazy | 3 | 148,149 bytes | 0.00213 s |

The lazy approach processes documents incrementally, while the eager approach stores them in memory.

The small corpus does not show a significant performance difference, and the results are inconclusive regarding memory usage.