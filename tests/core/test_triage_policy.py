"""Tests for the pure triage proposal rules (core/triage_policy.py)."""

from datetime import UTC, datetime, timedelta

from fleet.core.triage_policy import (
    CLOSE,
    COMMON_OPTIONS,
    EDIT_RETRY,
    IGNORE_24H,
    IGNORE_FOREVER,
    RESOLVE_MERGE,
    RETRY_OPUS,
    RETRY_SAME,
    digest_text,
    ignore_active,
    is_repair_answer,
    merge_conflict_info,
    propose,
    repair_running_label,
)


def _attempts(**overrides):
    base = {"rounds": {}, "rate_limited": False, "stderr_tail": None}
    base.update(overrides)
    return base


def test_default_proposal_offers_common_options():
    p = propose({"id": "t1", "title": "T"}, _attempts(), None, "failed 1 time")
    assert p.options == COMMON_OPTIONS
    assert "t1" in p.text


def test_rate_limit_suggests_switch():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rate_limited=True),
        None,
        "rate limited",
    )
    assert "rate limit" in p.text.lower()
    assert RETRY_OPUS in p.options


def test_stall_rounds_suggest_stronger_model():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rounds={"stall": 2}),
        None,
        "stalled 2 times",
    )
    assert "stronger model" in p.text
    assert p.options == COMMON_OPTIONS


def test_context_exhausted_suggests_split():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rounds={"context": 3}),
        None,
        "too large for one worker",
    )
    assert "split" in p.text
    assert p.options == COMMON_OPTIONS


def test_result_blocked_quotes_report_verbatim():
    result = {
        "status": "blocked",
        "blocked_reason": "need API key",
        "open_questions": ["which env?"],
    }
    p = propose({"id": "t1", "title": "T"}, _attempts(), result, "agent blocked")
    assert "need API key" in p.text
    assert "which env?" in p.text
    assert p.options == COMMON_OPTIONS


def test_failure_exhausted_shows_stderr_tail():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rounds={"failure": 3}, stderr_tail="boom\ntraceback"),
        None,
        "retry limit exhausted",
    )
    assert "boom" in p.text
    assert RETRY_SAME in p.options and RETRY_OPUS in p.options
    assert EDIT_RETRY in p.options and CLOSE in p.options
    assert IGNORE_24H in p.options and IGNORE_FOREVER in p.options


def test_rule_priority_rate_limit_first():
    p = propose(
        {"id": "t1", "title": "T"},
        _attempts(rounds={"stall": 2, "failure": 3}, rate_limited=True),
        None,
        "blocked",
    )
    assert "rate limit" in p.text.lower()


def test_ignore_active():
    assert ignore_active("forever")
    assert ignore_active("FOREVER")
    future = (datetime.now(tz=UTC) + timedelta(hours=1)).isoformat()
    assert ignore_active(future)
    past = (datetime.now(tz=UTC) - timedelta(hours=1)).isoformat()
    assert not ignore_active(past)
    assert not ignore_active(None)
    assert not ignore_active("")
    assert not ignore_active("not-a-date")


def test_digest_text_lists_tasks():
    text = digest_text(
        [
            {"id": "a", "title": "A", "blocked_reason": "r1"},
            {"id": "b", "title": "B", "blocked_reason": "r2"},
        ]
    )
    assert "a" in text and "b" in text and "r1" in text


_CONFLICT_REASON = "merge conflict into main; resolve on branch fleet/t9 then close"


def _conflict_task(**overrides):
    task = {
        "id": "t9",
        "title": "T",
        "merge_conflict": {
            "repo_root": "/repo",
            "base_ref": "main",
            "branch": "fleet/t9",
            "files": ["a.txt", "b.txt"],
        },
    }
    task.update(overrides)
    return task


def test_merge_conflict_rule_wins_over_exhausted_rounds():
    result = {"status": "blocked", "blocked_reason": "need help", "open_questions": []}
    p = propose(
        _conflict_task(),
        _attempts(rounds={"stall": 5, "failure": 9, "context": 9}, rate_limited=True),
        result,
        _CONFLICT_REASON,
    )
    assert p.options[0] == RESOLVE_MERGE
    assert "repair worker" in p.text


def test_merge_conflict_option_order():
    p = propose(_conflict_task(), _attempts(), None, _CONFLICT_REASON)
    assert p.options == [RESOLVE_MERGE, RETRY_SAME, RETRY_OPUS, CLOSE, IGNORE_24H, IGNORE_FOREVER]
    assert EDIT_RETRY not in p.options


def test_merge_conflict_text_names_branch_base_and_files():
    p = propose(_conflict_task(), _attempts(), None, _CONFLICT_REASON)
    assert "`fleet/t9`" in p.text
    assert "`main`" in p.text
    assert "a.txt" in p.text and "b.txt" in p.text


def test_merge_conflict_text_tolerates_missing_info():
    p = propose({"id": "t9", "title": "T"}, _attempts(), None, _CONFLICT_REASON)
    assert p.options[0] == RESOLVE_MERGE
    assert "`fleet/t9`" in p.text
    assert "unknown" in p.text


def test_merge_conflict_running_repair_relabels_first_option():
    task = _conflict_task(repair_task_id="fake-001")
    p = propose(task, _attempts(), None, _CONFLICT_REASON)
    assert p.options[0] == repair_running_label("fake-001")
    assert "fake-001" in p.options[0]


def test_is_repair_answer():
    assert is_repair_answer(RESOLVE_MERGE)
    assert is_repair_answer(repair_running_label("fake-001"))
    assert not is_repair_answer(RETRY_SAME)
    assert not is_repair_answer(None)


def test_merge_conflict_info_parses():
    info = merge_conflict_info(_conflict_task(repair_task_id="fake-001"))
    assert info is not None
    assert (info.repo_root, info.base_ref, info.branch) == ("/repo", "main", "fleet/t9")
    assert info.files == ("a.txt", "b.txt")
    assert info.repair_task_id == "fake-001"


def test_merge_conflict_info_tolerates_missing_fields():
    info = merge_conflict_info({"id": "t", "merge_conflict": {"files": ["a", 7, None, ""]}})
    assert info is not None
    assert info.repo_root == "" and info.base_ref == "" and info.branch == ""
    assert info.files == ("a",)
    assert info.repair_task_id is None


def test_merge_conflict_info_none_when_absent():
    assert merge_conflict_info({"id": "t"}) is None
    assert merge_conflict_info({"id": "t", "merge_conflict": ["not", "a", "dict"]}) is None
