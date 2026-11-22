
import argparse
import time
import tracemalloc
from collections import Counter
from itertools import islice
from pathlib import Path

from findex.corpus import iter_documents
from findex.tokenize import tokenize


def analyze(root: Path, limit: int | None = None) -> dict:
    start_time = time.perf_counter()
    tracemalloc.start()

    documents = iter_documents(root)

    if limit is not None:
        documents = islice(documents, limit)

    total_documents = 0
    total_tokens = 0
    frequencies = Counter()

    for document in documents:
        total_documents += 1

        for token in tokenize(document.text):
            total_tokens += 1
            frequencies[token] += 1

    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    elapsed_time = time.perf_counter() - start_time

    return {
        "documents": total_documents,
        "tokens": total_tokens,
        "vocabulary": len(frequencies),
        "top_terms": frequencies.most_common(50),
        "elapsed_time": elapsed_time,
        "peak_memory": peak_memory,
    }

    
def analyze_eager(root: Path, limit: int | None = None) -> dict:
    start_time = time.perf_counter()
    tracemalloc.start()

    documents = iter_documents(root)

    if limit is not None:
        documents = islice(documents, limit)

    documents = list(documents)

    token_lists = [
        list(tokenize(document.text))
        for document in documents
    ]

    frequencies = Counter(
        token
        for tokens in token_lists
        for token in tokens
    )

    total_tokens = sum(len(tokens) for tokens in token_lists)

    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    elapsed_time = time.perf_counter() - start_time

    return {
        "documents": len(documents),
        "tokens": total_tokens,
        "vocabulary": len(frequencies),
        "top_terms": frequencies.most_common(50),
        "elapsed_time": elapsed_time,
        "peak_memory": peak_memory,
    }



def main():
    parser = argparse.ArgumentParser(
        description="Analyze a text corpus."
    )

    parser.add_argument("root", type=Path)
    parser.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()

    results = analyze(args.root, args.limit)

    print(f"Documents: {results['documents']}")
    print(f"Total tokens: {results['tokens']}")
    print(f"Vocabulary size: {results['vocabulary']}")

    print("\nTop 50 terms:")
    for term, count in results["top_terms"]:
        print(f"{term}: {count}")

    print(f"\nElapsed time: {results['elapsed_time']:.4f} seconds")
    print(
        f"Peak memory: "
        f"{results['peak_memory'] / (1024 * 1024):.2f} MB"
    )


if __name__ == "__main__":
    main()
