"""Tests for `fleet flow` commands (unit under test: cli/flow.py).

Every test points FLEET_HOME at tmp_path and points `flows_folders` at a
tmp catalog folder (one valid flow, one `manual: false` flow, one invalid
file, one tool), so no test ever touches the real fleet home.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from fleet.cli.main import app
from fleet.runs.run_dir import NO_ITEM
from fleet.runs.store import RunStore, StepStatus, runs_db_path
from tests.cli.conftest import runner

wide_runner = CliRunner(env={"COLUMNS": "200"})

DEMO_YAML = """\
fleet_flow: 2
description: Demo flow.
"on":
  manual: true
inputs:
  repo:
    required: true
    description: Repo path.
  feature:
    default: main
defaults:
  coder: opencode
steps:
  build:
    prompt: Build {{ inputs.repo }}.
    outputs: [units]
  test:
    needs: [build]
    prompt: Test it.
    checks:
      - name: fresh
        tool: mytool
        args: {reply: x}
        on_fail: retry
"""

HAND_YAML = """\
fleet_flow: 2
description: Hand-started only when allowed.
"on":
  manual: false
steps:
  build:
    prompt: Build it.
"""

BROKEN_YAML = """\
description: Missing the fleet_flow marker.
steps: []
"""

TOOL_YAML = """\
fleet_tool: 2
description: Parse a reply.
command: ["echo", "{{ args.reply }}"]
args:
  reply: {required: true}
output: text
timeout: 30
"""


def _catalog(tmp_path: Path) -> Path:
    """Catalog folder with one valid flow, one manual:false flow, junk, a tool."""
    folder = tmp_path / "catalog"
    flows_dir = folder / "flows"
    tools_dir = folder / "tools"
    flows_dir.mkdir(parents=True)
    tools_dir.mkdir(parents=True)
    (flows_dir / "demo.yaml").write_text(DEMO_YAML, encoding="utf-8")
    (flows_dir / "hand.yaml").write_text(HAND_YAML, encoding="utf-8")
    (flows_dir / "broken.yaml").write_text(BROKEN_YAML, encoding="utf-8")
    (tools_dir / "mytool.yaml").write_text(TOOL_YAML, encoding="utf-8")
    return folder


def _use_home(tmp_path: Path, monkeypatch) -> Path:
    """Point FLEET_HOME at tmp_path with runtime.toml aimed at the catalog."""
    folder = _catalog(tmp_path)
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    (tmp_path / "runtime.toml").write_text(
        f'flows_folders = ["{folder.as_posix()}"]\n', encoding="utf-8"
    )
    return folder


def _store(tmp_path: Path) -> RunStore:
    """Run store rooted at the tmp fleet home."""
    return RunStore(runs_db_path(tmp_path))


def _start_demo(tmp_path: Path, *args: str) -> str:
    """Start the demo flow via the CLI and return the printed run id."""
    result = runner.invoke(app, ["flow", "run", "demo", *[a for pair in args for a in pair]])
    assert result.exit_code == 0, result.output
    run_id = result.output.strip()
    assert run_id.startswith("run-")
    return run_id


def test_list_shows_flow_and_warns_about_invalid(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    result = wide_runner.invoke(app, ["flow", "list"])
    assert result.exit_code == 0, result.output
    assert "demo" in result.output
    assert "manual" in result.output
    assert "broken" in result.stderr  # catalog problem as a stderr warning


def test_list_json_has_starts_enabled_source(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["flow", "list", "--json"])
    assert result.exit_code == 0, result.output
    rows = {row["name"]: row for row in json.loads(result.stdout)}
    assert rows["demo"]["starts"] == "manual"
    assert rows["demo"]["enabled"] is True
    assert rows["demo"]["source"].endswith("demo.yaml")


def test_show_prints_steps_and_checks(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["flow", "show", "demo"])
    assert result.exit_code == 0, result.output
    assert "build" in result.output
    assert "needs: build" in result.output
    assert "fresh" in result.output
    assert "(required)" in result.output
    assert "(default: main)" in result.output


def test_show_json_round_trips_and_unknown_is_not_found(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["flow", "show", "demo", "--json"])
    assert result.exit_code == 0, result.output
    assert set(json.loads(result.stdout)["steps"]) == {"build", "test"}
    assert runner.invoke(app, ["flow", "show", "nope"]).exit_code == 3


def test_validate_ok_and_problems(tmp_path: Path, monkeypatch) -> None:
    folder = _use_home(tmp_path, monkeypatch)
    good = runner.invoke(app, ["flow", "validate", str(folder / "flows" / "demo.yaml")])
    assert good.exit_code == 0, good.output
    assert "ok" in good.output
    tool = runner.invoke(app, ["flow", "validate", str(folder / "tools" / "mytool.yaml")])
    assert tool.exit_code == 0, tool.output
    bad = runner.invoke(app, ["flow", "validate", str(folder / "flows" / "broken.yaml")])
    assert bad.exit_code == 1
    assert "fleet_flow" in bad.output


def test_run_creates_run_with_inputs(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    run_id = _start_demo(tmp_path, ("--input", "repo=/tmp/x"), ("--input", "feature=f"))
    run = _store(tmp_path).get_run(run_id)
    assert run is not None
    assert run.inputs == {"repo": "/tmp/x", "feature": "f"}
    assert (tmp_path / "runs" / run_id / "flow.yaml").is_file()


def test_run_missing_required_input_fails(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["flow", "run", "demo"])
    assert result.exit_code == 1
    assert "repo" in result.output


def test_run_malformed_input_fails_usage(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["flow", "run", "demo", "--input", "repo"])
    assert result.exit_code == 2


def test_run_manual_false_fails(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    result = runner.invoke(app, ["flow", "run", "hand"])
    assert result.exit_code == 1
    assert "manual" in result.output


def test_runs_and_status_show_run(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    run_id = _start_demo(tmp_path, ("--input", "repo=/tmp/x"))
    listed = wide_runner.invoke(app, ["flow", "runs"])
    assert listed.exit_code == 0, listed.output
    assert run_id in listed.output
    assert "running" in listed.output
    filtered = wide_runner.invoke(app, ["flow", "runs", "--flow", "demo", "--status", "running"])
    assert filtered.exit_code == 0, filtered.output
    assert run_id in filtered.output
    as_json = runner.invoke(app, ["flow", "runs", "--json"])
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout)[0]["flow"] == "demo"
    assert runner.invoke(app, ["flow", "runs", "--status", "bogus"]).exit_code == 2
    detail = runner.invoke(app, ["flow", "status", run_id])
    assert detail.exit_code == 0, detail.output
    assert "build" in detail.output
    assert "pending" in detail.output
    assert "repo=/tmp/x" in detail.output
    detail_json = runner.invoke(app, ["flow", "status", run_id, "--json"])
    assert detail_json.exit_code == 0, detail_json.output
    payload = json.loads(detail_json.stdout)
    assert payload["id"] == run_id
    assert {item["step"] for item in payload["steps"]} == {"build", "test"}
    assert runner.invoke(app, ["flow", "status", "run-20000101-xxxxxx"]).exit_code == 3


def test_status_outputs_prints_finished_outputs(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    run_id = _start_demo(tmp_path, ("--input", "repo=/tmp/x"))
    store = _store(tmp_path)
    store.set_step_status(
        run_id, "build", NO_ITEM, StepStatus.succeeded, datetime.now(UTC).isoformat()
    )
    out_dir = tmp_path / "runs" / run_id / "build" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "outputs.json").write_text('{"units": ["a"]}', encoding="utf-8")
    detail = runner.invoke(app, ["flow", "status", run_id, "--outputs"])
    assert detail.exit_code == 0, detail.output
    assert "units" in detail.output


def test_cancel_marks_run_cancelled(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    run_id = _start_demo(tmp_path, ("--input", "repo=/tmp/x"))
    result = runner.invoke(app, ["flow", "cancel", run_id, "--reason", "stop"])
    assert result.exit_code == 0, result.output
    assert "cancelled" in result.output
    assert _store(tmp_path).get_run(run_id).status.value == "cancelled"
    detail = runner.invoke(app, ["flow", "status", run_id])
    assert detail.exit_code == 0, detail.output
    assert "cancelled" in detail.output


def test_retry_refuses_pending_and_works_on_failed(tmp_path: Path, monkeypatch) -> None:
    _use_home(tmp_path, monkeypatch)
    run_id = _start_demo(tmp_path, ("--input", "repo=/tmp/x"))
    refused = runner.invoke(app, ["flow", "retry", run_id, "build"])
    assert refused.exit_code == 1
    assert "pending" in refused.output
    store = _store(tmp_path)
    store.set_step_status(
        run_id, "build", NO_ITEM, StepStatus.failed, datetime.now(UTC).isoformat(), "boom"
    )
    retried = runner.invoke(app, ["flow", "retry", run_id, "build"])
    assert retried.exit_code == 0, retried.output
    assert store.get_step_run(run_id, "build", NO_ITEM).status is StepStatus.ready
    assert runner.invoke(app, ["flow", "retry", run_id, "missing"]).exit_code == 3
