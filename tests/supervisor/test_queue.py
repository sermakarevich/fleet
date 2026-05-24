import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet.queue import BeadsError, BeadsQueue


def test_claim_next_empty_ready_list_returns_none(queue: BeadsQueue) -> None:
    """claim_next returns None when no ready tasks exist."""
    with patch.object(queue, "_bd", return_value={"data": []}):
        result = queue.claim_next("worker-1")
    assert result is None


def test_claim_next_contention_at_most_one_winner(tmp_path: Path) -> None:
    """At most one claimer wins the same task when two race simultaneously."""
    task_data = [{"id": "t-001", "title": "Task 1", "description": None}]
    claim_counter = {"n": 0}
    counter_lock = threading.Lock()

    def shared_mock_bd(*args: str, json_envelope: bool = True, actor: str | None = None) -> dict | None:
        if args and args[0] == "ready":
            return {"data": task_data}
        if "--claim" in args:
            with counter_lock:
                claim_counter["n"] += 1
                if claim_counter["n"] > 1:
                    raise BeadsError("contention: already claimed by another worker")
            return None
        return None

    q1 = BeadsQueue(repo_root=tmp_path)
    q2 = BeadsQueue(repo_root=tmp_path)
    results: list = [None, None]
    barrier = threading.Barrier(2)

    def run(q: BeadsQueue, idx: int) -> None:
        barrier.wait()  # synchronize so both call claim_next at the same time
        results[idx] = q.claim_next(f"worker-{idx}")

    with patch.object(q1, "_bd", side_effect=shared_mock_bd):
        with patch.object(q2, "_bd", side_effect=shared_mock_bd):
            t1 = threading.Thread(target=run, args=(q1, 0))
            t2 = threading.Thread(target=run, args=(q2, 1))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

    non_none = [r for r in results if r is not None]
    assert len(non_none) <= 1


def test_claim_next_reads_cwd_from_meta_file(tmp_path: Path) -> None:
    """When a task has a meta file with cwd, claim_next surfaces it on the Task."""
    q = BeadsQueue(repo_root=tmp_path)
    task_meta_dir = tmp_path / "tasks" / "t-001"
    task_meta_dir.mkdir(parents=True)
    (task_meta_dir / "task.json").write_text(
        '{"cwd": "/abs/project"}', encoding="utf-8"
    )

    task_data = [{"id": "t-001", "title": "Task 1", "description": None}]

    def mock_bd(*args: str, json_envelope: bool = True, actor: str | None = None) -> dict | None:
        if args and args[0] == "ready":
            return {"data": task_data}
        return None

    with patch.object(q, "_bd", side_effect=mock_bd):
        task = q.claim_next("worker-1")

    assert task is not None
    assert task.cwd == "/abs/project"


def test_claim_next_no_meta_file_yields_none_cwd(tmp_path: Path) -> None:
    """Tasks without a meta file have cwd=None (back-compat)."""
    q = BeadsQueue(repo_root=tmp_path)
    task_data = [{"id": "t-002", "title": "Task 2", "description": None}]

    def mock_bd(*args: str, json_envelope: bool = True, actor: str | None = None) -> dict | None:
        if args and args[0] == "ready":
            return {"data": task_data}
        return None

    with patch.object(q, "_bd", side_effect=mock_bd):
        task = q.claim_next("worker-1")

    assert task is not None
    assert task.cwd is None


def test_create_task_with_cwd_writes_meta_file(tmp_path: Path) -> None:
    """create_task with cwd= writes <repo_root>/tasks/<id>/task.json with the cwd."""
    q = BeadsQueue(repo_root=tmp_path)

    def mock_bd(*args: str, json_envelope: bool = True, actor: str | None = None) -> dict | None:
        if "create" in args:
            return {"data": {"id": "t-100"}}
        if "show" in args:
            return {"data": {"id": "t-100", "title": "x", "description": None, "status": "open"}}
        return None

    with patch.object(q, "_bd", side_effect=mock_bd):
        task = q.create_task("Title", cwd="/some/project")

    meta_path = tmp_path / "tasks" / "t-100" / "task.json"
    assert meta_path.exists()
    import json
    assert json.loads(meta_path.read_text())["cwd"] == "/some/project"
    assert task.cwd == "/some/project"


def test_freeze_coder_model_writes_coder_and_model(tmp_path: Path) -> None:
    """freeze_coder_model persists the effective coder and model into task.json."""
    q = BeadsQueue(repo_root=tmp_path)
    task_dir = tmp_path / "tasks" / "t-001"
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        '{"id": "t-001", "cwd": "/some/project"}', encoding="utf-8"
    )

    q.freeze_coder_model("t-001", "claude", "opus")

    import json
    meta = json.loads((task_dir / "task.json").read_text())
    assert meta["coder"] == "claude"
    assert meta["model"] == "opus"
    assert meta["cwd"] == "/some/project"  # existing fields preserved


def test_freeze_coder_model_creates_meta_if_missing(tmp_path: Path) -> None:
    """freeze_coder_model works even when task.json does not yet exist."""
    q = BeadsQueue(repo_root=tmp_path)
    task_dir = tmp_path / "tasks" / "t-002"
    task_dir.mkdir(parents=True)

    q.freeze_coder_model("t-002", "agy", "GPT-OSS 120B")

    import json
    meta = json.loads((task_dir / "task.json").read_text())
    assert meta["coder"] == "agy"
    assert meta["model"] == "GPT-OSS 120B"


def test_freeze_coder_model_overwrites_prior_values(tmp_path: Path) -> None:
    """A second freeze_coder_model call updates the stored values."""
    q = BeadsQueue(repo_root=tmp_path)
    task_dir = tmp_path / "tasks" / "t-003"
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        '{"id": "t-003", "coder": "agy", "model": "GPT-OSS 120B"}', encoding="utf-8"
    )

    q.freeze_coder_model("t-003", "claude", "sonnet")

    import json
    meta = json.loads((task_dir / "task.json").read_text())
    assert meta["coder"] == "claude"
    assert meta["model"] == "sonnet"


def test_set_overrides_writes_only_provided_fields(tmp_path: Path) -> None:
    """set_overrides writes coder/model independently, preserving other fields."""
    q = BeadsQueue(repo_root=tmp_path)
    task_dir = tmp_path / "tasks" / "t-ovr-1"
    task_dir.mkdir(parents=True)
    (task_dir / "task.json").write_text(
        '{"id": "t-ovr-1", "cwd": "/x", "model": "opus"}', encoding="utf-8"
    )

    q.set_overrides("t-ovr-1", coder="agy")

    import json
    meta = json.loads((task_dir / "task.json").read_text())
    assert meta["coder"] == "agy"
    assert meta["model"] == "opus"  # untouched
    assert meta["cwd"] == "/x"      # untouched


def test_set_overrides_noop_when_both_none(tmp_path: Path) -> None:
    """set_overrides leaves task.json alone when no override is supplied."""
    q = BeadsQueue(repo_root=tmp_path)
    task_dir = tmp_path / "tasks" / "t-ovr-2"
    task_dir.mkdir(parents=True)
    before = '{"id": "t-ovr-2", "cwd": "/x"}'
    (task_dir / "task.json").write_text(before, encoding="utf-8")

    q.set_overrides("t-ovr-2")

    assert (task_dir / "task.json").read_text() == before


def test_set_overrides_creates_meta_if_missing(tmp_path: Path) -> None:
    """set_overrides creates task.json when none exists yet."""
    q = BeadsQueue(repo_root=tmp_path)

    q.set_overrides("t-ovr-3", coder="claude", model="opus")

    import json
    meta = json.loads((tmp_path / "tasks" / "t-ovr-3" / "task.json").read_text())
    assert meta["coder"] == "claude"
    assert meta["model"] == "opus"


def test_beads_error_raised_on_nonzero_bd_exit(tmp_path: Path) -> None:
    """BeadsError is raised when the bd subprocess exits with non-zero status."""
    q = BeadsQueue(repo_root=tmp_path)
    failed = subprocess.CompletedProcess(
        args=["bd", "show", "nonexistent"],
        returncode=1,
        stdout="",
        stderr="issue not found",
    )
    with patch("fleet.queue.subprocess.run", return_value=failed):
        with pytest.raises(BeadsError, match="issue not found"):
            q._bd("show", "nonexistent")
