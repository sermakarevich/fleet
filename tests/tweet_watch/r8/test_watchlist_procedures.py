"""R8 watchlist procedures (F5-F7, F12-F13, F28): add/remove rules and empty states."""


def test_add_handle_format_rules(runbook_lower: str) -> None:
    assert "one" in runbook_lower and "per line" in runbook_lower
    assert "blank lines" in runbook_lower
    assert "#" in runbook_lower and "comment" in runbook_lower
    assert '"@"' in runbook_lower or "leading `@`" in runbook_lower or "leading @" in runbook_lower


def test_add_handle_example_not_comma_list(runbook_lower: str) -> None:
    assert "comma" in runbook_lower or "cloneisjun" in runbook_lower


def test_new_handle_needs_no_state_edit(runbook_lower: str) -> None:
    assert (
        "all candidates are new" in runbook_lower
        or "missing" in runbook_lower
        and "state" in runbook_lower
    )


def test_remove_handle_leaves_state_alone(runbook_lower: str) -> None:
    assert (
        "leave state alone" in runbook_lower
        or "leave" in runbook_lower
        and "state" in runbook_lower
    )


def test_remove_forbids_hand_editing_state(runbook_lower: str) -> None:
    assert "watchlist.md" in runbook_lower
    assert (
        "hand-edit" in runbook_lower
        or "hand-merg" in runbook_lower
        or "risks corrupting" in runbook_lower
    )


def test_empty_watchlist_is_valid_quiet_config(runbook_lower: str) -> None:
    assert "quiet" in runbook_lower
    assert "zero" in runbook_lower or "empty" in runbook_lower


def test_empty_watchlist_never_reseeds(runbook_lower: str) -> None:
    assert (
        "never overwritten" in runbook_lower
        or "never" in runbook_lower
        and "re-seed" in runbook_lower
        or "re-seeding" in runbook_lower
    )


def test_concurrent_edits_are_serial(runbook_lower: str) -> None:
    assert "re-read" in runbook_lower or "serial" in runbook_lower
