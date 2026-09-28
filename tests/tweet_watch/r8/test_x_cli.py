"""R8 x CLI commands (F4, F17): exact invocations plus failure troubleshooting."""


def test_watch_add_invocation_exact(runbook_text: str) -> None:
    assert "x watch add user:<handle>" in runbook_text


def test_watch_check_invocation_exact(runbook_text: str) -> None:
    assert "x watch check --format json" in runbook_text


def test_no_ad_hoc_text_munging_substitute(runbook_lower: str) -> None:
    assert "json" in runbook_lower
    assert (
        "text-munging" in runbook_lower
        or "instead of json parsing" in runbook_lower
        or "json parsing" in runbook_lower
    )


def test_cli_failure_fails_loud_with_handle_named(runbook_lower: str) -> None:
    assert "fail" in runbook_lower
    assert "handle" in runbook_lower


def test_failed_scope_leaves_state_untouched(runbook_lower: str) -> None:
    assert "state" in runbook_lower
    assert "untouched" in runbook_lower or "retries" in runbook_lower or "next run" in runbook_lower


def test_never_fabricates_tweets(runbook_lower: str) -> None:
    assert (
        "fabricat" in runbook_lower or "invent" in runbook_lower or "cached tweets" in runbook_lower
    )
