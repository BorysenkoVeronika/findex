from findex.tokenize import tokenize


def test_case_insensitive():
    assert list(tokenize("Python PYTHON")) == ["python", "python"]


def test_english_words():
    assert list(tokenize("Hello world")) == ["hello", "world"]


def test_combining_marks():
    assert list(tokenize("nai\u0308ve")) == ["naïve"]


def test_punctuation():
    assert list(tokenize("Hello, world!")) == ["hello", "world"]


def test_empty_text():
    assert list(tokenize("")) == []


def test_hyphen():
    assert list(tokenize("well-known")) == ["well", "known"]


def test_apostrophe():
    assert list(tokenize("don't")) == ["don", "t"]


def test_underscore():
    assert list(tokenize("Python_3")) == ["python", "3"]

def test_cyrillic_text():
    assert list(tokenize("Привет МИР")) == ["привет", "мир"]