"""R8 edge cases and concurrency (F14, F16, F18, F21, F23-F29)."""


def test_backlog_emits_everything_once(runbook_lower: str) -> None:
    assert (
        "backlog" in runbook_lower
        or "missed runs" in runbook_lower
        or "new tweets" in runbook_lower
    )
    assert (
        "no batching" in runbook_lower
        or "no sampling" in runbook_lower
        or "each" in runbook_lower
        and "proposal" in runbook_lower
    )


def test_backlog_never_skips_via_state_edits(runbook_lower: str) -> None:
    assert "triage" in runbook_lower or "confirm" in runbook_lower


def test_requirements_win_over_stale_runbook(runbook_lower: str) -> None:
    assert "r1" in runbook_lower or "requirements" in runbook_lower
    assert "mismatch" in runbook_lower or "stale" in runbook_lower


def test_missing_interests_aborts_proposals(runbook_lower: str) -> None:
    assert "interests.md" in runbook_lower
    assert "abort" in runbook_lower


def test_permission_errors_fix_perms_never_sudo(runbook_lower: str) -> None:
    assert "permission" in runbook_lower
    assert "sudo" in runbook_lower
    assert "chmod" in runbook_lower or "chown" in runbook_lower


def test_outage_ages_out_dedupe_window(runbook_lower: str) -> None:
    assert "3-day" in runbook_lower or "3 day" in runbook_lower
    assert "outage" in runbook_lower or "skew" in runbook_lower or "aged out" in runbook_lower


def test_deleted_source_link_gets_dead_link_note(runbook_lower: str) -> None:
    assert "404" in runbook_lower or "dead-link" in runbook_lower or "dead link" in runbook_lower


def test_confirmation_without_id_stores_nothing(runbook_lower: str) -> None:
    assert "store nothing" in runbook_lower or "stores nothing" in runbook_lower
    assert "invent" in runbook_lower or "pending" in runbook_lower


def test_external_reply_still_proposes(runbook_lower: str) -> None:
    assert "manual reply" in runbook_lower or "outside the worker" in runbook_lower
    assert "still proposes" in runbook_lower or "backstop" in runbook_lower


def test_overlapping_runs_have_no_locking(runbook_lower: str) -> None:
    assert "overlap" in runbook_lower
    assert "lockfile" in runbook_lower or "no-locking" in runbook_lower or "lock" in runbook_lower


def test_duplicate_proposal_is_accepted_backstop(runbook_lower: str) -> None:
    assert "duplicate proposal" in runbook_lower


def test_state_race_last_writer_wins_no_hand_merge(runbook_lower: str) -> None:
    assert "last-writer-wins" in runbook_lower or "last writer" in runbook_lower
    assert "hand-merg" in runbook_lower or "forbid" in runbook_lower
