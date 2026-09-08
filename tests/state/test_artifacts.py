"""Tests for `state.artifacts.read_artifacts`: the I/O side of launch
planning that builds the `core.launch.ArtifactSnapshot` fed to `plan_launch`.
"""

from __future__ import annotations

from pathlib import Path

from fleet.state.artifacts import read_artifacts
from tests.helpers.task_dir import make_attempt, make_task_dir

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "src" / "fleet" / "templates"


def _stub(task_id: str) -> str:
    return (_TEMPLATES_DIR / "STATE.md.tmpl").read_text(encoding="utf-8").format(
        task_id=task_id
    )


def _seed_state(task_dir: Path, task_id: str) -> None:
    (task_dir / "STATE.md").write_text(_stub(task_id), encoding="utf-8")


def test_stub_state_is_flagged_as_stub(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-1")
    _seed_state(task_dir, "t-1")

    snap = read_artifacts(task_dir, "t-1")

    assert snap.state_is_stub is True
    assert snap.latest_result is None
    assert snap.latest_result_is_missing is False


def test_missing_state_counts_as_stub(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-2"
    task_dir.mkdir(parents=True)

    snap = read_artifacts(task_dir, "t-2")

    assert snap.state_is_stub is True
    assert snap.state_text == ""


def test_edited_state_is_not_a_stub(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-3")
    _seed_state(task_dir, "t-3")
    (task_dir / "STATE.md").write_text("## Done\n- real work\n", encoding="utf-8")

    snap = read_artifacts(task_dir, "t-3")

    assert snap.state_is_stub is False
    assert "real work" in snap.state_text


def test_no_previous_attempt_means_result_not_missing(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-4")
    _seed_state(task_dir, "t-4")

    snap = read_artifacts(task_dir, "t-4", before_n=1)

    assert snap.latest_result_is_missing is False
    assert snap.latest_result is None


def test_previous_attempt_without_result_snapshot_is_missing(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-5")
    _seed_state(task_dir, "t-5")
    make_attempt(task_dir, 1, outcome="failure", reason="crash")

    snap = read_artifacts(task_dir, "t-5", before_n=2)

    assert snap.latest_result_is_missing is True
    assert snap.latest_result is None


def test_previous_attempt_with_valid_result_snapshot_is_parsed(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-6")
    _seed_state(task_dir, "t-6")
    attempt_dir = make_attempt(task_dir, 1, outcome="partial", reason="next_step: go")
    (attempt_dir / "RESULT.json").write_text(
        '{"schema": 1, "status": "partial", "summary": "did some", "next_step": "go"}',
        encoding="utf-8",
    )

    snap = read_artifacts(task_dir, "t-6", before_n=2)

    assert snap.latest_result_is_missing is False
    assert snap.latest_result == {
        "schema": 1,
        "status": "partial",
        "summary": "did some",
        "next_step": "go",
    }


def test_before_n_selects_the_attempt_strictly_before_it(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-7")
    _seed_state(task_dir, "t-7")
    make_attempt(task_dir, 1, outcome="failure", reason="crash")
    attempt2 = make_attempt(task_dir, 2, outcome="partial", reason="next_step: continue")
    (attempt2 / "RESULT.json").write_text('{"schema": 1, "status": "partial"}', encoding="utf-8")

    # Planning attempt 3 should look at attempt 2 (the most recent completed one).
    snap = read_artifacts(task_dir, "t-7", before_n=3)

    assert snap.latest_result == {"schema": 1, "status": "partial"}


def test_malformed_result_snapshot_counts_as_missing(tmp_path: Path) -> None:
    """"missing" means "no *parseable* RESULT.json" — malformed content counts too."""
    task_dir = make_task_dir(tmp_path, "t-8")
    _seed_state(task_dir, "t-8")
    attempt_dir = make_attempt(task_dir, 1, outcome="failure", reason="crash")
    (attempt_dir / "RESULT.json").write_text("not json", encoding="utf-8")

    snap = read_artifacts(task_dir, "t-8", before_n=2)

    assert snap.latest_result_is_missing is True
    assert snap.latest_result is None


def test_old_dir_without_state_falls_back_to_legacy(tmp_path: Path) -> None:
    """Pre-STATE.md dirs render artifacts/{PLAN,HANDOFF,KNOWLEDGE}.md as state."""
    task_dir = make_task_dir(tmp_path, "t-9")
    artifacts = task_dir / "artifacts"
    (artifacts / "PLAN.md").write_text("# plan\n", encoding="utf-8")
    (artifacts / "HANDOFF.md").write_text("## Done\n- old work\n", encoding="utf-8")
    (artifacts / "KNOWLEDGE.md").write_text("## Facts\n- old fact\n", encoding="utf-8")

    snap = read_artifacts(task_dir, "t-9")

    assert snap.state_is_stub is False
    assert "old work" in snap.state_text
    assert "old fact" in snap.state_text
