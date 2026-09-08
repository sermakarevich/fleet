"""Tests for `state.artifacts.read_artifacts`: the I/O side of launch
planning that builds the `core.launch.ArtifactSnapshot` fed to `plan_launch`.
"""

from __future__ import annotations

from pathlib import Path

from fleet.state.artifacts import read_artifacts
from tests.helpers.task_dir import make_attempt, make_task_dir

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "src" / "fleet" / "templates"


def _stub(name: str, task_id: str) -> str:
    return (_TEMPLATES_DIR / f"{name}.tmpl").read_text(encoding="utf-8").format(task_id=task_id)


def _seed_stubs(task_dir: Path, task_id: str) -> None:
    artifacts_dir = task_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for name in ("PLAN.md", "HANDOFF.md", "KNOWLEDGE.md"):
        (artifacts_dir / name).write_text(_stub(name, task_id), encoding="utf-8")


def test_stub_artifacts_are_flagged_as_stubs(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-1")
    _seed_stubs(task_dir, "t-1")

    snap = read_artifacts(task_dir, "t-1")

    assert snap.handoff_is_stub is True
    assert snap.knowledge_is_stub is True
    assert snap.plan_is_stub is True
    assert snap.latest_summary_text is None
    assert snap.latest_result is None
    assert snap.latest_result_is_missing is False


def test_missing_artifacts_dir_counts_as_stub(tmp_path: Path) -> None:
    task_dir = tmp_path / "tasks" / "t-2"
    task_dir.mkdir(parents=True)

    snap = read_artifacts(task_dir, "t-2")

    assert snap.handoff_is_stub is True
    assert snap.handoff_text == ""


def test_edited_handoff_is_not_a_stub(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-3")
    _seed_stubs(task_dir, "t-3")
    (task_dir / "artifacts" / "HANDOFF.md").write_text("Done: real work\n", encoding="utf-8")

    snap = read_artifacts(task_dir, "t-3")

    assert snap.handoff_is_stub is False
    assert "real work" in snap.handoff_text
    # Other artifacts remain untouched stubs.
    assert snap.knowledge_is_stub is True


def test_no_previous_attempt_means_result_not_missing(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-4")
    _seed_stubs(task_dir, "t-4")

    snap = read_artifacts(task_dir, "t-4", before_n=1)

    assert snap.latest_result_is_missing is False
    assert snap.latest_result is None
    assert snap.latest_summary_text is None


def test_previous_attempt_without_result_json_is_missing(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-5")
    _seed_stubs(task_dir, "t-5")
    attempt_dir = make_attempt(task_dir, 1, outcome="failure", reason="crash")
    (attempt_dir / "SUMMARY.md").write_text("# Attempt 1 summary\n", encoding="utf-8")

    snap = read_artifacts(task_dir, "t-5", before_n=2)

    assert snap.latest_result_is_missing is True
    assert snap.latest_result is None
    assert snap.latest_summary_text == "# Attempt 1 summary\n"


def test_previous_attempt_with_valid_result_is_parsed(tmp_path: Path) -> None:
    task_dir = make_task_dir(tmp_path, "t-6")
    _seed_stubs(task_dir, "t-6")
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
    _seed_stubs(task_dir, "t-7")
    make_attempt(task_dir, 1, outcome="failure", reason="crash")
    attempt2 = make_attempt(task_dir, 2, outcome="partial", reason="next_step: continue")
    (attempt2 / "SUMMARY.md").write_text("# Attempt 2 summary\n", encoding="utf-8")
    (attempt2 / "RESULT.json").write_text('{"schema": 1, "status": "partial"}', encoding="utf-8")

    # Planning attempt 3 should look at attempt 2 (the most recent completed one).
    snap = read_artifacts(task_dir, "t-7", before_n=3)

    assert snap.latest_summary_text == "# Attempt 2 summary\n"
    assert snap.latest_result == {"schema": 1, "status": "partial"}


def test_malformed_result_json_counts_as_missing(tmp_path: Path) -> None:
    """"missing" means "no *parseable* RESULT.json" — malformed content counts too."""
    task_dir = make_task_dir(tmp_path, "t-8")
    _seed_stubs(task_dir, "t-8")
    attempt_dir = make_attempt(task_dir, 1, outcome="failure", reason="crash")
    (attempt_dir / "RESULT.json").write_text("not json", encoding="utf-8")

    snap = read_artifacts(task_dir, "t-8", before_n=2)

    assert snap.latest_result_is_missing is True
    assert snap.latest_result is None
