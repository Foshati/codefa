from codefa.api.web_tools.parsers import extract_url


def test_extract_url_basic_http():
    assert extract_url("http://example.com") == "http://example.com"


def test_extract_url_basic_https():
    assert extract_url("https://example.com") == "https://example.com"


def test_extract_url_embedded_in_text():
    assert extract_url("Here is a link: https://example.com check it out.") == "https://example.com"


def test_extract_url_trailing_punctuation_dot():
    assert extract_url("Check this: https://example.com.") == "https://example.com"


def test_extract_url_trailing_punctuation_comma():
    assert extract_url("Go to https://example.com, and then...") == "https://example.com"


def test_extract_url_trailing_punctuation_parenthesis():
    assert extract_url("This is neat (https://example.com)") == "https://example.com"


def test_extract_url_trailing_punctuation_bracket():
    assert extract_url("Link [https://example.com]") == "https://example.com"


def test_extract_url_trailing_punctuation_multiple():
    assert extract_url("Multiple https://example.com).,]") == "https://example.com"


def test_extract_url_no_url_fallback():
    assert extract_url("   Just some text with no url   ") == "Just some text with no url"


def test_extract_url_no_url_empty():
    assert extract_url("") == ""
    assert extract_url("   ") == ""
