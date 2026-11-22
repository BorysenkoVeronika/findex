"""Lab 08: compare classic and vectorized rankings and compressed postings."""

from pathlib import Path

import pytest

from findex.index import build_index
from findex.numpy_search import as_arrays, load_compressed, save_compressed, search_numpy
from findex.search import BM25, TfIdf, search


@pytest.mark.parametrize("query", ["python", "java", "python OR java", "python programming", "NOT java"])
@pytest.mark.parametrize("scorer", [BM25(), TfIdf()])
def test_same_rankings(corpus: Path, query: str, scorer: BM25 | TfIdf) -> None:
    index = build_index(corpus)
    original = search(index, query, scorer=scorer)
    optimized = search_numpy(index, query, scorer=scorer)
    assert [result.doc_id for result in original] == [result.doc_id for result in optimized]
    for left, right in zip(original, optimized):
        assert left.score == pytest.approx(right.score, abs=1e-10)


def test_compressed_memmap(corpus: Path, tmp_path: Path) -> None:
    index = build_index(corpus)
    save_compressed(index, tmp_path)
    original = as_arrays(index)
    restored = load_compressed(tmp_path)
    assert original.keys() == restored.keys()
    for term in original:
        assert original[term].doc_ids.tolist() == restored[term].doc_ids.tolist()
        assert original[term].tfs.tolist() == restored[term].tfs.tolist()
    assert [r.doc_id for r in search_numpy(index, "python OR java", arrays=restored)] == [
        r.doc_id for r in search(index, "python OR java")
    ]
