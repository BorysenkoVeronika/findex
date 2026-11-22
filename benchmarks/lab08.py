from __future__ import annotations

import argparse
import cProfile
import csv
from pathlib import Path
import pstats
import statistics
import time

from findex.corpus import Document, iter_documents
from findex.index import build_from_documents, build_index
from findex.numpy_search import as_arrays, load_compressed, save_compressed, search_numpy
from findex.search import search
from findex.query import parse


def median_ms(fn, repeats: int) -> float:
    fn()  # warmup
    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        values.append((time.perf_counter() - start) * 1000)
    return statistics.median(values)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("docs"))
    parser.add_argument("--repeats", type=int, default=15)
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("--repeats must be >= 3")
    args.out.mkdir(parents=True, exist_ok=True)
    index = build_index(args.corpus)
    arrays = as_arrays(index)
    queries = [
        ("common term", "programming"),
        ("rare term", "python"),
        ("three-term query", "python OR java OR javascript"),
    ]
    rows = []
    for label, query in queries:

        def classic():
            return search(index, query, k=10)

        def vector():
            return search_numpy(index, query, k=10, arrays=arrays)

        old = classic()
        new = vector()
        if [r.doc_id for r in old] != [r.doc_id for r in new]:
            raise AssertionError(f"Ranking differs: {query}")
        t_old = median_ms(classic, args.repeats)
        t_new = median_ms(vector, args.repeats)
        rows.append(
            {
                "query": label,
                "matches": len(parse(query).evaluate(index)),
                "classic_ms": round(t_old, 6),
                "numpy_ms": round(t_new, 6),
                "speedup": round(t_old / t_new, 4),
            }
        )
    with (args.out / "lab08-speedup.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("Query, matches, classic ms, NumPy ms, speedup")
    for row in rows:
        print(f"{row['query']}, {row['matches']}, {row['classic_ms']}, {row['numpy_ms']}, {row['speedup']}x")

    # Construct exactly 10x as many valid documents without writing a huge corpus.
    originals = list(iter_documents(args.corpus))
    expanded = [
        Document(f"{doc.doc_id}-{repetition}", doc.path, doc.text) for repetition in range(10) for doc in originals
    ]
    big = build_from_documents(expanded)
    compact = args.out / "lab08-postings"
    save_compressed(big, compact)
    restored = load_compressed(compact)
    assert [r.doc_id for r in search_numpy(big, "python OR java", arrays=restored)] == [
        r.doc_id for r in search(big, "python OR java")
    ]
    print(
        f"10x corpus: {big.num_docs} documents, compressed postings: {(compact / 'postings.i32').stat().st_size} bytes"
    )

    with cProfile.Profile() as profile:
        for _ in range(100):
            search(index, "python OR java OR javascript")
        build_from_documents(expanded)
    profile.dump_stats(str(args.out / "lab08-cprofile.prof"))
    with (args.out / "lab08-cprofile.txt").open("w", encoding="utf-8") as f:
        stats = pstats.Stats(profile, stream=f)
        stats.sort_stats("cumulative").print_stats(25)
    print("Saved CSV, cProfile stats, and compressed postings in", args.out)


if __name__ == "__main__":
    main()
