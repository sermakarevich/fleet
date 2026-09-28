"""Tests for `fleet flow run --wait/--json/--reuse` (unit under test: cli/flow.py).

Every test points FLEET_HOME at tmp_path and reuses the catalog fixtures of
`tests/cli/test_flow_cli.py`, so no test ever touches the real fleet home.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from fleet.cli.main import app
from fleet.runs.run_dir import NO_ITEM
from fleet.runs.store import RunStatus, StepStatus
from tests.cli.conftest import runner
from tests.cli.test_flow_cli import _store, _use_home


def _start_demo(*args: str) -> str:
    """Start the demo flow via the CLI and return the printed run id."""
    result = runner.invoke(app, ["flow", "run", "demo", *args])
    assert result.exit_code == 0, result.output
    run_id = result.output.strip()
    assert run_id.startswith("run-")
    return run_id


def test_inputs_json_merges_over_input_and_rejects_non_object(tmp_path: Path, monkeypatch) -> None:
    """--inputs-json wins over --input; a non-object exits USAGE."""
    _use_home(tmp_path, monkeypatch)
    merged = runner.invoke(
        app,
        [
            "flow",
            "run",
            "demo",
            "--input",
            "repo=/tmp/old",
            "--input",
            "feature=old",
            "--inputs-json",
            '{"repo": "/tmp/new"}',
            "--json",
        ],
    )
    assert merged.exit_code == 0, merged.output
    assert json.loads(merged.stdout)["inputs"] == {"repo": "/tmp/new", "feature": "old"}
    bad_list = runner.invoke(app, ["flow", "run", "demo", "--inputs-json", '["a"]'])
    assert bad_list.exit_code == 2
    bad_values = runner.invoke(app, ["flow", "run", "demo", "--inputs-json", '{"repo": 1}'])
    assert bad_values.exit_code == 2
    bad_syntax = runner.invoke(app, ["flow", "run", "demo", "--inputs-json", "{not json"])
    assert bad_syntax.exit_code == 2


def _finish_newest_after_first_poll(tmp_path: Path, store, status: RunStatus):
    """Sleep fake marking the newest unfinished demo run *status* once.

    The waiting invoke starts its own run, so the helper flips whatever run
    the CLI is actually waiting on (writing a build outputs.json first for
    the succeeded case), pretending the supervisor finished it mid-poll.
    """

    def _fake(seconds: float) -> None:
        """Flip the newest unfinished demo run exactly once, then idle."""
        if _fake.done:  # type: ignore[attr-defined]
            return
        _fake.done = True  # type: ignore[attr-defined]
        for candidate in store.list_runs(flow="demo", limit=10):
            if candidate.status in (
                RunStatus.succeeded,
                RunStatus.failed,
                RunStatus.cancelled,
            ):
                continue
            if status is RunStatus.succeeded:
                out_dir = tmp_path / "runs" / candidate.id / "build" / "outputs"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "outputs.json").write_text('{"units": ["a"]}', encoding="utf-8")
                store.set_step_status(
                    candidate.id,
                    "build",
                    NO_ITEM,
                    StepStatus.succeeded,
                    datetime.now(UTC).isoformat(),
                )
            store.finish_run(candidate.id, status, "test", datetime.now(UTC).isoformat())
            break

    _fake.done = False  # type: ignore[attr-defined]
    return _fake


def test_wait_json_reports_succeeded_run_with_outputs(tmp_path: Path, monkeypatch) -> None:
    """--wait --json prints one document with status and step outputs."""
    _use_home(tmp_path, monkeypatch)
    store = _store(tmp_path)
    monkeypatch.setattr(
        time, "sleep", _finish_newest_after_first_poll(tmp_path, store, RunStatus.succeeded)
    )
    result = runner.invoke(
        app,
        ["flow", "run", "demo", "--input", "repo=/tmp/x", "--wait", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["id"].startswith("run-")
    assert payload["status"] == "succeeded"
    assert payload["reused"] is False
    assert payload["outputs"]["build"] == {"units": ["a"]}
    assert {item["step"] for item in payload["steps"]} == {"build", "test"}


def test_wait_json_on_failed_run_prints_json_and_exits_1(tmp_path: Path, monkeypatch) -> None:
    """--wait --json still prints the document when the run failed."""
    _use_home(tmp_path, monkeypatch)
    store = _store(tmp_path)
    monkeypatch.setattr(
        time, "sleep", _finish_newest_after_first_poll(tmp_path, store, RunStatus.failed)
    )
    result = runner.invoke(
        app, ["flow", "run", "demo", "--input", "repo=/tmp/x", "--wait", "--json"]
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["id"].startswith("run-")
    assert payload["status"] == "failed"


def test_reuse_attaches_to_identical_succeeded_run(tmp_path: Path, monkeypatch) -> None:
    """--reuse returns the existing run id without inserting a new row."""
    _use_home(tmp_path, monkeypatch)
    run_id = _start_demo("--input", "repo=/tmp/x")
    store = _store(tmp_path)
    store.finish_run(run_id, RunStatus.succeeded, "", datetime.now(UTC).isoformat())
    before = len(store.list_runs(flow="demo", limit=500))
    result = runner.invoke(
        app, ["flow", "run", "demo", "--input", "repo=/tmp/x", "--reuse", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["id"] == run_id
    assert payload["reused"] is True
    assert len(_store(tmp_path).list_runs(flow="demo", limit=500)) == before


def test_timeout_exits_nonzero_without_hanging(tmp_path: Path, monkeypatch) -> None:
    """--timeout on a run that never finishes exits non-zero promptly."""
    _use_home(tmp_path, monkeypatch)
    seen: list[float] = []
    monkeypatch.setattr(time, "sleep", seen.append)
    result = runner.invoke(
        app,
        ["flow", "run", "demo", "--input", "repo=/tmp/x", "--wait", "--timeout", "0.01"],
    )
    assert result.exit_code != 0, result.output
    assert "run-" in result.output
    assert seen, "the CLI must poll through time.sleep"
