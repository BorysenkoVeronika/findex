"""Property-based specifications (included when the dev dependencies are installed)."""

import pytest
from findex.tokenize import tokenize
from findex.search import merge_and, merge_or

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st  # noqa: E402


@given(st.text())
def test_tokens_never_empty(text):
    assert all(token for token in tokenize(text))


@given(st.lists(st.integers(min_value=0, max_value=100)), st.lists(st.integers(min_value=0, max_value=100)))
def test_merge_and_matches_sets(a, b):
    assert merge_and(sorted(set(a)), sorted(set(b))) == sorted(set(a) & set(b))


@given(st.lists(st.integers(min_value=0, max_value=100)), st.lists(st.integers(min_value=0, max_value=100)))
def test_merge_or_matches_sets(a, b):
    assert merge_or(sorted(set(a)), sorted(set(b))) == sorted(set(a) | set(b))
