import sys
import time
import statistics
from pathlib import Path

from findex.parallel import build_parallel

print("GIL enabled:", sys._is_gil_enabled())

times = []

for i in range(3):
    start = time.perf_counter()

    index = build_parallel(
        Path("benchmark_data"),
        executor="threads",
        workers=6,
    )

    elapsed = time.perf_counter() - start
    times.append(elapsed)

    print(f"Run {i + 1}: {elapsed:.3f}s")

print(f"Median: {statistics.median(times):.3f}s")
print(f"Documents: {len(index.doc_meta)}")
print(f"Terms: {len(index.postings)}")
