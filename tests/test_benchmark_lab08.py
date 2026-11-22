"""Repeatable fixture benchmarks used by pytest-benchmark."""

from pathlib import Path

import pytest

pytest.importorskip("pytest_benchmark")

from findex.index import build_index
from findex.numpy_search import as_arrays, search_numpy
from findex.search import search


def test_benchmark_build_index(benchmark, corpus: Path) -> None:
    index = benchmark(build_index, corpus)
    assert index.num_docs > 0


def test_benchmark_search(benchmark, corpus: Path) -> None:
    index = build_index(corpus)
    results = benchmark(search, index, "python")
    assert isinstance(results, list)


def test_benchmark_numpy_search(benchmark, corpus: Path) -> None:
    index = build_index(corpus)
    arrays = as_arrays(index)
    results = benchmark(search_numpy, index, "python", arrays=arrays)
    assert isinstance(results, list)
