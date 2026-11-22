from findex.index import build_index
from findex.search import merge_and, merge_or, boolean_search
from findex.store import save, load


def test_index_and_search(corpus):
    ix = build_index(corpus)
    assert ix.num_docs == 3
    assert ix.df("python") == 2
    assert boolean_search(ix, "python", engine="set") == [0, 2]
    assert boolean_search(ix, "python", engine="merge") == [0, 2]


def test_merge():
    assert merge_and([0, 1, 4], [1, 3, 4]) == [1, 4]
    assert merge_or([0, 1, 4], [1, 3, 4]) == [0, 1, 3, 4]


def test_persistence(corpus, tmp_path):
    ix = build_index(corpus)
    for ext in ("bin", "json"):
        dest = tmp_path / ("index." + ext)
        save(ix, dest)
        assert load(dest).postings == ix.postings
