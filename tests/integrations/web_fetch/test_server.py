from fleet.integrations.web_fetch.server import _TextExtractor, web_fetch


def test_text_extractor_strips_script_and_style():

    p = _TextExtractor()
    p.feed(
        "<html><body><script>var x=1</script>"
        "<p>Hello</p><style>a{color:red}</style><p>World</p></body></html>"
    )
    text = p.text()
    assert "Hello" in text
    assert "World" in text
    assert "var x" not in text  # script body excluded
    assert "color:red" not in text  # style body excluded


def test_web_fetch_rejects_non_http_scheme():

    out = web_fetch("file:///etc/passwd", "anything")
    assert out["url"] == "file:///etc/passwd"
    assert "error" in out
    assert "fetch failed" in out["error"]  # offline: rejected before any network call
