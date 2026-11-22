# Findex — Labs 01–03

Python search engine built progressively through Lab 03.

## Usage

```bash
python -m findex.index data/ --out index.bin --positions
python -m findex.search index.bin "python OR java"
```

Run from an installed environment or set `PYTHONPATH=src`.

## Lab 01 — Iterators and the Corpus

The original `iter_documents` generator streams UTF-8 `.txt` files; unreadable files log a warning and are skipped. `tokenize` uses NFC normalization, case folding, and Unicode alphanumeric tokens, separating hyphens, apostrophes and underscores. The `stats` module compares eager and lazy processing.

| Version | Documents | Peak memory | Time |
|---|---:|---:|---:|
| Eager | 3 | 139,695 bytes | 0.00178 s |
| Lazy | 3 | 148,149 bytes | 0.00213 s |

These original measurements on the tiny corpus do not demonstrate a meaningful memory advantage.

## Lab 02 — Inverted Index and Memory

`Index` contains sorted `Posting(doc_id, tf, positions)` lists, per-document lengths and metadata. Boolean search supports implicit AND, OR, NOT, and both sorted-list merge and set engines. Pickle (`.bin`) and JSON (`.json`) persistence are supported. **Only unpickle files from trusted sources:** pickle deserialization can execute code.

### Posting representation experiment

Local measurement of the three-document corpus (Python 3.13.5, one run). These are memory allocations for constructing the compared representations, not full indexing peak RSS.

| Representation | Build peak | Pickle size | Load time |
|---|---:|---:|---:|
| Plain dataclass | 27,168 bytes | 4,353 bytes | 0.278 ms |
| Slotted dataclass | 18,040 bytes | 3,750 bytes | 0.231 ms |
| `array('I')` pairs | 16,800 bytes | 4,629 bytes | 0.142 ms |

Plain dataclass objects retain instance dictionaries; slotted dataclasses omit them, and arrays store compact integers without per-posting objects. On this very small sample, pickle's container and serialization overhead makes the array file larger, despite its lower construction memory. The experiment source is `benchmarks/memory.py`.


### Merge-vs-set and serialization measurements

Measured on the provided three-document corpus during the complete-project audit. Times are median of seven calls, in milliseconds; these tiny-call timings are sensitive to noise.

| Query term | Merge (ms) | Set (ms) |
|---|---:|---:|
| python | 0.01317 | 0.00375 |
| programming | 0.00353 | 0.00401 |
| java | 0.00425 | 0.00313 |
| gosling | 0.00435 | 0.00366 |

| Format | File bytes | Save (ms) | Load (ms) |
|---|---:|---:|---:|
| json | 5494 | 0.3950 | 0.1825 |
| bin | 6039 | 0.5823 | 0.2593 |

Positions increased binary index size from 5497 to 6039 bytes on this sample.

## Lab 03 — Object Model, Query Language and Ranking

`Index` implements the mapping protocol and exposes `num_docs`, `avg_doc_length`, `doc_length`, and `df`. Query nodes (`Term`, `Phrase`, `And`, `Or`, `Not`) form a dataclass AST with `&`, `|`, `~`, and `.evaluate(index)`. The parser supports precedence, quoted phrases, NOT, and parentheses. `TfIdf` and `BM25(k1=1.5, b=0.75)` implement a swappable scorer interface. Top-k results include document titles and highlighted context snippets. Query parsing uses an LRU cache of 256 expressions. Ranking saturation and length normalization are tested.


### Hand-labeled precision@5 (three-document corpus)

The labels were written against the actual sample documents. Each query has one relevant document, so the maximum possible precision@5 is 0.20; this is not a realistic search-quality benchmark.

| Query | Relevant title | TF-IDF P@5 | BM25 P@5 |
|---|---|---:|---:|
| python | document | 0.20 | 0.20 |
| garbage collection | document | 0.20 | 0.20 |
| dynamic typing | document | 0.20 | 0.20 |
| java | document2 | 0.20 | 0.20 |
| gosling | document2 | 0.20 | 0.20 |
| oracle | document2 | 0.20 | 0.20 |
| javascript | document3 | 0.20 | 0.20 |
| typescript | document3 | 0.20 | 0.20 |
| github | document3 | 0.20 | 0.20 |
| web | document3 | 0.20 | 0.20 |

Ranking sanity checks (also covered by automated tests): BM25 term-frequency gains diminish under repetition; length normalization favors a shorter document at equal term frequency; uncommon terms have greater inverse-document-frequency influence. For this very small corpus, ties and query-specific lengths can affect observed order.

