"""R8 schedule identity (F2, F19): exact name/cadence/overlap/coder plus reinstall."""

EXPECTED_CREATE = "fleet schedule create --name tweet-watch"


def test_schedule_name_is_tweet_watch(runbook_text: str) -> None:
    assert "tweet-watch" in runbook_text


def test_cron_cadence_is_every_30_minutes(runbook_text: str) -> None:
    assert "*/30 * * * *" in runbook_text


def test_overlap_skip_documented(runbook_text: str) -> None:
    assert "--overlap skip" in runbook_text


def test_coder_is_opencode(runbook_text: str) -> None:
    assert "opencode" in runbook_text


def test_exact_reinstall_command(runbook_text: str) -> None:
    assert EXPECTED_CREATE in runbook_text
    assert "*/30 * * * *" in runbook_text
    assert "--overlap skip" in runbook_text


def test_reverify_lists_schedule(runbook_text: str) -> None:
    assert "fleet schedule list" in runbook_text


def test_forbids_variant_name_backup_entry(runbook_lower: str) -> None:
    assert "tweet-watch" in runbook_lower
    assert "duplicat" in runbook_lower or "second" in runbook_lower
    assert "variant" in runbook_lower or "different name" in runbook_lower or "backup" in runbook_lower
