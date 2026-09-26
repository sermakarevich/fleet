"""R8 verify-a-run (F9, F15): concrete success signals and the length rule."""


def test_verify_names_schedule_list_signal(runbook_text: str) -> None:
    assert "fleet schedule list" in runbook_text
    assert "tweet-watch" in runbook_text


def test_verify_defines_quiet_run(runbook_lower: str) -> None:
    assert "quiet" in runbook_lower
    assert "zero proposals" in runbook_lower or "zero new files" in runbook_lower


def test_verify_defines_high_run(runbook_lower: str) -> None:
    assert "ask_human" in runbook_lower
    assert "link" in runbook_lower and "draft" in runbook_lower


def test_verify_counts_one_call_per_high(runbook_lower: str) -> None:
    assert "one" in runbook_lower and "per" in runbook_lower and "high" in runbook_lower


def test_over_limit_drafts_rewritten_not_truncated(runbook_lower: str) -> None:
    assert "rewrite" in runbook_lower or "trim" in runbook_lower
    assert "mid-word" in runbook_lower or "truncate" in runbook_lower
