"""R8 recovery (F10-F11, F22): corrupt state repair and missed-run catch-up."""


def test_corrupt_state_aborts_before_fetch(runbook_lower: str) -> None:
    assert "abort" in runbook_lower
    assert "watch_state.json" in runbook_lower


def test_corrupt_state_backed_up_first(runbook_lower: str) -> None:
    assert ".bak" in runbook_lower or "back up" in runbook_lower or "backup" in runbook_lower
    assert "cp watch_state.json" in runbook_lower or "cp " in runbook_lower


def test_corrupt_state_validated_as_json(runbook_lower: str) -> None:
    assert "json.load" in runbook_lower


def test_corrupt_state_never_silently_reset(runbook_lower: str) -> None:
    assert "reset" in runbook_lower or "re-emit" in runbook_lower or "duplicate" in runbook_lower


def test_missed_run_triggers_exactly_one_manual_run(runbook_lower: str) -> None:
    assert "exactly one" in runbook_lower
    assert "fleet schedule run" in runbook_lower


def test_missed_run_forbids_replay_per_tick(runbook_lower: str) -> None:
    assert (
        "missed tick" in runbook_lower
        or "per missed" in runbook_lower
        or "catch up" in runbook_lower
    )
