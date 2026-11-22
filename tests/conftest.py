from pathlib import Path
import pytest
from findex.index import build_index


@pytest.fixture
def corpus(tmp_path: Path):
    (tmp_path/'one.txt').write_text('python python async code', encoding='utf-8')
    (tmp_path/'two.txt').write_text('python Java code', encoding='utf-8')
    (tmp_path/'three.txt').write_text('async code from another program', encoding='utf-8')
    return tmp_path


@pytest.fixture
def ix(corpus):
    return build_index(corpus)
