from findex.index import build_index
from findex.query import parse, And, Or, Term
from findex.search import search, BM25, TfIdf


def test_query_parser():
    assert parse("a OR b c") == Or(Term("a"), And(Term("b"), Term("c")))


def test_rank(corpus):
    ix = build_index(corpus)
    assert search(ix, "python", scorer=BM25())[0].doc_id == 0
    assert search(ix, "python", scorer=TfIdf())
