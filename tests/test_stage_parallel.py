from findex.index import build_index
from findex.parallel import build_parallel


def test_parallel(corpus):
    serial = build_index(corpus)
    for method in ("serial", "threads", "processes"):
        actual = build_parallel(corpus, workers=2, executor=method)
        assert actual.postings == serial.postings
        assert actual.doc_meta == serial.doc_meta
