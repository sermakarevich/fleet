import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import structlog

from fleet.logging_setup import TaskLog, append_event, open_task_log, setup_supervisor_logger
from fleet.schemas import Event


@pytest.fixture(autouse=True)
def reset_structlog():
    yield
    structlog.reset_defaults()


def _ts() -> datetime:
    return datetime.now(tz=timezone.utc)


def test_setup_supervisor_logger_writes_jsonl(tmp_path: Path):
    log = setup_supervisor_logger(tmp_path)
    log.info("test_event", foo="bar")

    date = datetime.now().strftime("%Y-%m-%d")
    fleet_path = tmp_path / f"fleet-{date}.jsonl"
    assert fleet_path.exists()

    lines = fleet_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "test_event"
    assert record["foo"] == "bar"
    assert "timestamp" in record
    assert record["level"] == "info"


def test_setup_supervisor_logger_binds_supervisor_context(tmp_path: Path):
    log = setup_supervisor_logger(tmp_path)
    log.info("ping")

    date = datetime.now().strftime("%Y-%m-%d")
    fleet_path = tmp_path / f"fleet-{date}.jsonl"
    record = json.loads(fleet_path.read_text().strip())
    assert record["component"] == "supervisor"
    assert "pid" in record


def test_open_task_log_creates_jsonl_and_stderr_files(tmp_path: Path):
    task_dir = tmp_path / "t-001"
    with open_task_log(task_dir, "t-001") as tl:
        tl.log.info("subprocess_started")

    assert (task_dir / "log.jsonl").exists()
    assert (task_dir / "log.stderr").exists()


def test_open_task_log_jsonl_contains_bound_fields(tmp_path: Path):
    task_dir = tmp_path / "t-001"
    with open_task_log(task_dir, "t-001") as tl:
        tl.log.info("subprocess_started")

    record = json.loads((task_dir / "log.jsonl").read_text().strip())
    assert record["event"] == "subprocess_started"
    assert record["task_id"] == "t-001"
    assert "pid" in record


def test_open_task_log_returns_task_log_instance(tmp_path: Path):
    tl = open_task_log(tmp_path / "t-001", "t-001")
    assert isinstance(tl, TaskLog)
    assert hasattr(tl, "log")
    assert hasattr(tl, "stderr_file")
    tl.__exit__(None, None, None)


def test_open_task_log_appends_across_runs(tmp_path: Path):
    task_dir = tmp_path / "t-001"
    with open_task_log(task_dir, "t-001") as tl:
        tl.log.info("first")
    with open_task_log(task_dir, "t-001") as tl:
        tl.log.info("second")

    lines = (task_dir / "log.jsonl").read_text().splitlines()
    assert len(lines) == 2


def test_append_event_writes_one_json_line(tmp_path: Path):
    task_dir = tmp_path / "task"
    evt = Event(kind="result", raw={"x": 1}, ts=_ts(), session_id="sess-1")
    append_event(task_dir, evt)

    events_path = task_dir / "events.jsonl"
    assert events_path.exists()
    record = json.loads(events_path.read_text().strip())
    assert record["kind"] == "result"
    assert record["session_id"] == "sess-1"
    assert record["raw"] == {"x": 1}


def test_append_event_never_truncates_prior_content(tmp_path: Path):
    task_dir = tmp_path / "task"
    ts = _ts()
    evt1 = Event(kind="result", raw={}, ts=ts, session_id="sess-a")
    evt2 = Event(kind="error", raw={}, ts=ts, session_id="sess-b")
    append_event(task_dir, evt1)
    append_event(task_dir, evt2)

    lines = (task_dir / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == "result"
    assert json.loads(lines[1])["kind"] == "error"


def test_append_event_redacts_credentials(tmp_path: Path):
    task_dir = tmp_path / "task"
    evt = Event(
        kind="result",
        raw={"ANTHROPIC_API_KEY": "sk-secret-123", "safe": "value"},
        ts=_ts(),
    )
    append_event(task_dir, evt)

    record = json.loads((task_dir / "events.jsonl").read_text().strip())
    assert record["raw"]["ANTHROPIC_API_KEY"] == "<redacted>"
    assert record["raw"]["safe"] == "value"


def test_append_event_does_not_emit_attempt_field(tmp_path: Path):
    task_dir = tmp_path / "task"
    evt = Event(kind="result", raw={}, ts=_ts())
    append_event(task_dir, evt)
    record = json.loads((task_dir / "events.jsonl").read_text().strip())
    assert "attempt" not in record
