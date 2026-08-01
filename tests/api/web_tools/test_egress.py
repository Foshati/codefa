from codefa.api.web_tools.egress import web_fetch_allowed_scheme_set

def test_web_fetch_allowed_scheme_set_normal():
    assert web_fetch_allowed_scheme_set("http,https") == frozenset({"http", "https"})

def test_web_fetch_allowed_scheme_set_casing():
    assert web_fetch_allowed_scheme_set("HTTP, HtTpS ") == frozenset({"http", "https"})

def test_web_fetch_allowed_scheme_set_whitespace_and_empty():
    assert web_fetch_allowed_scheme_set("http,,https") == frozenset({"http", "https"})
    assert web_fetch_allowed_scheme_set(" , http , ") == frozenset({"http"})

def test_web_fetch_allowed_scheme_set_single():
    assert web_fetch_allowed_scheme_set("http") == frozenset({"http"})

def test_web_fetch_allowed_scheme_set_none():
    assert web_fetch_allowed_scheme_set("") == frozenset()
    assert web_fetch_allowed_scheme_set("   ") == frozenset()
