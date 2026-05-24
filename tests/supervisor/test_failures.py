from pathlib import Path

from fleet.failures import failure_count, increment_failure


def test_failure_count_zero_when_missing(tmp_path: Path):
    assert failure_count(tmp_path / "t-001") == 0


def test_increment_failure_creates_and_increments(tmp_path: Path):
    task_dir = tmp_path / "t-001"
    assert increment_failure(task_dir) == 1
    assert increment_failure(task_dir) == 2
    assert failure_count(task_dir) == 2
    assert (task_dir / ".failures").exists()


def test_failure_counter_isolated_per_task(tmp_path: Path):
    dir1 = tmp_path / "t-001"
    dir2 = tmp_path / "t-002"
    increment_failure(dir1)
    increment_failure(dir2)
    increment_failure(dir2)
    assert failure_count(dir1) == 1
    assert failure_count(dir2) == 2


def test_failure_count_ignores_unreadable_counter(tmp_path: Path):
    task_dir = tmp_path / "t-001"
    task_dir.mkdir()
    (task_dir / ".failures").write_text("not-a-number")
    assert failure_count(task_dir) == 0
