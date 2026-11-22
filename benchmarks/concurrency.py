"""Lab 05: reproducible serial/threads/processes indexing benchmark.

Run from the findex project root:
    uv add --dev matplotlib
    uv run python benchmarks/concurrency.py --corpus benchmark_data

Results are saved in docs/lab05-benchmark.csv, docs/lab05-benchmark.json,
and docs/lab05-speedup.png. All figures describe the machine running this script.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


RESULTS = Path("docs")
MODES = ("serial", "threads", "processes")


def parent_peak_rss_bytes() -> int:
    """Peak resident set for the current benchmark subprocess (not children)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        )
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        memory = ProcessMemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(memory), memory.cb
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return int(memory.PeakWorkingSetSize)

    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak * (1 if sys.platform == "darwin" else 1024))


def single_run(corpus: Path, executor: str, workers: int) -> None:
    """Runs in a fresh process, so peak RSS is independent for each sample."""
    import findex.parallel as parallel

    merge_seconds = 0.0
    original_merge = parallel.merge

    def measured_merge(partials: Any) -> Any:
        nonlocal merge_seconds
        started = time.perf_counter()
        try:
            return original_merge(partials)
        finally:
            merge_seconds += time.perf_counter() - started

    # Only the parent merges partial indexes. Its module-level reference to
    # merge can be wrapped without changing worker functions or pickling.
    parallel.merge = measured_merge
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    index = parallel.build_parallel(corpus, executor=executor, workers=workers)
    wall_seconds = time.perf_counter() - wall_start
    cpu_seconds = time.process_time() - cpu_start

    result = {
        "executor": executor,
        "workers": workers,
        "documents": index.num_docs,
        "terms": len(index),
        "wall_s": wall_seconds,
        "parent_cpu_s": cpu_seconds,
        "parent_peak_rss_bytes": parent_peak_rss_bytes(),
        "merge_s": merge_seconds,
    }
    print(json.dumps(result), flush=True)


def run_subprocess(script: Path, corpus: Path, executor: str, workers: int) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--single",
            "--corpus",
            str(corpus),
            "--executor",
            executor,
            "--workers",
            str(workers),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Benchmark failed ({executor}/{workers}):\n{completed.stderr}\n{completed.stdout}"
        )
    if not completed.stdout.strip():
        raise RuntimeError(f"No measurements returned by {executor}/{workers}: {completed.stderr}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def make_plot(rows: list[dict[str, Any]], path: Path) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit(
            "Matplotlib is required for the speedup PNG. Install with: uv add --dev matplotlib"
        ) from exc

    fig, ax = plt.subplots(figsize=(8.5, 5))
    workers = sorted({int(row["workers"]) for row in rows})
    for executor in MODES:
        relevant = [r for r in rows if r["executor"] == executor]
        relevant.sort(key=lambda r: int(r["workers"]))
        if relevant:
            ax.plot(
                [r["workers"] for r in relevant],
                [r["speedup"] for r in relevant],
                marker="o",
                label=executor,
            )
    ax.plot(workers, workers, linestyle="--", color="grey", label="ideal linear")
    ax.set_xlabel("Workers")
    ax.set_ylabel("Speedup vs serial (1 worker)")
    ax.set_title("Findex Lab 05 — Indexing speedup")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("benchmark_data"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--executor", choices=MODES, default="serial", help=argparse.SUPPRESS)
    parser.add_argument("--workers", type=int, default=1, help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", type=Path, default=RESULTS)
    args = parser.parse_args()
    if not args.corpus.is_dir():
        parser.error(f"Corpus does not exist: {args.corpus}")
    if args.runs < 3 and not args.single:
        parser.error("Lab 05 requires at least three measured runs per configuration")

    corpus = args.corpus.resolve()
    if args.single:
        single_run(corpus, args.executor, args.workers)
        return

    cpu_count = os.cpu_count() or 1
    worker_counts = sorted({1, 2, 4, 8, cpu_count})
    jobs = [("serial", 1)] + [
        (executor, workers)
        for executor in ("threads", "processes")
        for workers in worker_counts
    ]
    script = Path(__file__).resolve()
    results: list[dict[str, Any]] = []
    all_samples: list[dict[str, Any]] = []
    expected_counts: tuple[int, int] | None = None
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Corpus: {corpus} | CPUs: {cpu_count} | measured runs/config: {args.runs}", flush=True)
    for executor, workers in jobs:
        print(f"{executor:9} workers={workers:2}: warming up...", end="", flush=True)
        run_subprocess(script, corpus, executor, workers)
        runs: list[dict[str, Any]] = []
        for iteration in range(1, args.runs + 1):
            sample = run_subprocess(script, corpus, executor, workers)
            counts = (int(sample["documents"]), int(sample["terms"]))
            if expected_counts is None:
                expected_counts = counts
            if counts != expected_counts:
                raise RuntimeError(f"Index sizes differ: expected {expected_counts}, got {counts}")
            sample["run"] = iteration
            runs.append(sample)
            all_samples.append(sample)
            print(f" {iteration}", end="", flush=True)

        med = lambda key: statistics.median(float(s[key]) for s in runs)
        wall_times = [float(s["wall_s"]) for s in runs]
        results.append({
            "executor": executor,
            "workers": workers,
            "runs": args.runs,
            "documents": runs[0]["documents"],
            "terms": runs[0]["terms"],
            "wall_median_s": med("wall_s"),
            "wall_min_s": min(wall_times),
            "wall_max_s": max(wall_times),
            "parent_cpu_median_s": med("parent_cpu_s"),
            "parent_peak_rss_median_mib": round(med("parent_peak_rss_bytes") / 1048576, 3),
            "merge_median_s": med("merge_s"),
        })
        print(f" | median {results[-1]['wall_median_s']:.3f}s", flush=True)

    baseline = next(row["wall_median_s"] for row in results if row["executor"] == "serial")
    for row in results:
        row["speedup"] = round(baseline / row["wall_median_s"], 4)

    csv_path = args.output_dir / "lab05-benchmark.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    json_path = args.output_dir / "lab05-benchmark.json"
    with json_path.open("w", encoding="utf-8") as stream:
        json.dump({
            "environment": {
                "python": sys.version,
                "platform": platform.platform(),
                "cpu_model": platform.processor(),
                "cpu_count": cpu_count,
                "corpus": str(corpus),
                "runs": args.runs,
                "rss_scope": "benchmark parent process only (excludes worker processes)",
                "cpu_scope": "benchmark parent process only (excludes worker processes)",
                "dataset_note": "Synthetic corpus if generated from repeated Lab 01 files",
            },
            "summary": results,
            "samples": all_samples,
        }, stream, indent=2)
    png_path = args.output_dir / "lab05-speedup.png"
    make_plot(results, png_path)

    print("\nExecutor     Workers  Wall median   CPU parent    RSS parent   Merge       Speedup")
    for row in results:
        print(
            f"{row['executor']:11} {row['workers']:>7}  "
            f"{row['wall_median_s']:>10.3f}s  {row['parent_cpu_median_s']:>10.3f}s  "
            f"{row['parent_peak_rss_median_mib']:>8.2f} MiB  "
            f"{row['merge_median_s']:>8.3f}s  {row['speedup']:>7.2f}x"
        )
    print(f"\nSaved: {csv_path}, {json_path}, {png_path}")
    print("NOTE: CPU and RSS refer only to the parent process, not all worker processes.")


if __name__ == "__main__":
    main()
