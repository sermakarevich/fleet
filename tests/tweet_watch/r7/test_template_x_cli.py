"""R7 template x CLI invocations (F4) and CLI failure handling (F16)."""

from __future__ import annotations

from tests.tweet_watch.r7.conftest import template_text


def test_template_documents_watch_add_invocation() -> None:
    assert "x watch add" in template_text()


def test_template_documents_check_with_json_format() -> None:
    assert "x watch check --format json" in template_text(), (
        "a missing --format json is a template bug, not something to paper "
        "over with ad-hoc parsing (R7-F4)"
    )


def test_template_instructs_fail_loud_on_cli_error() -> None:
    lowered = template_text().lower()
    assert any(word in lowered for word in ("fail", "error", "abort", "non-zero", "stop")), (
        "template must instruct fail-loud with the handle named (R7-F16)"
    )


def test_template_forbids_inventing_tweets() -> None:
    lowered = template_text().lower()
    assert any(word in lowered for word in ("fabricat", "invent", "never guess", "make up")), (
        "template must forbid cached/invented candidates (R7-F16)"
    )
