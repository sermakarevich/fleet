"""Tests for fleet.pool.tool_run (real tiny commands, no shell)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fleet.flows import tools
from fleet.flows.tools import Tool, ToolArg
from fleet.pool.tool_run import ToolResult, run_tool, write_step_outputs


def _environ() -> dict[str, str]:
    """A real environment for child processes (needs PATH for python3)."""
    return dict(os.environ)


def _json_tool(**overrides) -> Tool:
    """A tool running an inline python3 snippet with json output."""
    base: dict = {
        "name": "echoer",
        "command": ("python3", "-c", "import json; print(json.dumps({'hello': 'world'}))"),
        "output": "json",
    }
    base.update(overrides)
    return Tool(**base)


def test_success_json_parsed_and_files_written(tmp_path: Path) -> None:
    """Exit 0 parses stdout; stdout/stderr/tool.json land in the attempt dir."""
    attempt = tmp_path / "attempts" / "1"
    result = asyncio.run(
        run_tool(
            _json_tool(),
            {},
            cwd=tmp_path,
            attempt_dir=attempt,
            environ=_environ(),
        )
    )
    assert isinstance(result, ToolResult)
    assert result.ok and result.exit_code == 0
    assert result.output == {"hello": "world"}
    assert not result.timed_out
    assert (attempt / "stdout.txt").read_text(encoding="utf-8") == result.stdout
    assert '"hello"' in result.stdout
    assert (attempt / "stderr.txt").read_text(encoding="utf-8") == result.stderr
    recorded = json.loads((attempt / "tool.json").read_text(encoding="utf-8"))
    assert recorded["exit_code"] == 0
    assert recorded["timed_out"] is False
    assert recorded["command"][0] == "python3"
    assert recorded["duration_s"] == result.duration_s >= 0.0


def test_nonzero_exit_has_no_output(tmp_path: Path) -> None:
    """A failing command is not ok and yields no parsed output."""
    tool = Tool(
        name="failer",
        command=("python3", "-c", "import sys; print('oops'); sys.exit(3)"),
        output="text",
    )
    result = asyncio.run(
        run_tool(tool, {}, cwd=tmp_path, attempt_dir=tmp_path / "a", environ=_environ())
    )
    assert not result.ok
    assert result.exit_code == 3
    assert result.output is None
    assert "oops" in result.stdout
    assert not result.timed_out


def test_stdin_delivered_when_declared(tmp_path: Path, monkeypatch) -> None:
    """A rendered stdin body reaches the child on its stdin."""
    monkeypatch.setattr(tools, "stdin_for", lambda tool, given: "hello-stdin", raising=False)
    tool = Tool(
        name="catter",
        command=("python3", "-c", "import sys; print('got:' + sys.stdin.read())"),
        output="text",
    )
    try:
        result = asyncio.run(
            run_tool(tool, {}, cwd=tmp_path, attempt_dir=tmp_path / "a", environ=_environ())
        )
    finally:
        monkeypatch.undo()
    assert result.ok
    assert "got:hello-stdin" in result.stdout


def test_stdin_closed_when_absent(tmp_path: Path) -> None:
    """Without a stdin body the child reads EOF at once."""
    tool = Tool(
        name="reader",
        command=("python3", "-c", "import sys; print(repr(sys.stdin.read()))"),
        output="text",
    )
    result = asyncio.run(
        run_tool(tool, {}, cwd=tmp_path, attempt_dir=tmp_path / "a", environ=_environ())
    )
    assert result.ok
    assert result.stdout.strip() == "''"


def test_timeout_kills(tmp_path: Path) -> None:
    """A slow command is killed: timed_out with no exit code."""
    tool = Tool(
        name="sleeper",
        command=("python3", "-c", "import time; time.sleep(5)"),
        output="text",
        timeout=120,
    )
    result = asyncio.run(
        run_tool(
            tool,
            {},
            cwd=tmp_path,
            attempt_dir=tmp_path / "a",
            environ=_environ(),
            timeout_s=0.2,
        )
    )
    assert result.timed_out
    assert result.exit_code is None
    assert not result.ok
    assert result.output is None
    assert result.duration_s < 4.0
    recorded = json.loads((tmp_path / "a" / "tool.json").read_text(encoding="utf-8"))
    assert recorded["timed_out"] is True
    assert recorded["exit_code"] is None


def test_missing_env_refused(tmp_path: Path) -> None:
    """Unset env vars refuse early, naming every missing name."""
    tool = Tool(
        name="needy",
        command=("python3", "-c", "print('never')"),
        env=("FLEET_TEST_MISSING_A", "FLEET_TEST_MISSING_B"),
        output="text",
    )
    environ = {k: v for k, v in _environ().items() if not k.startswith("FLEET_TEST_MISSING_")}
    result = asyncio.run(
        run_tool(tool, {}, cwd=tmp_path, attempt_dir=tmp_path / "a", environ=environ)
    )
    assert not result.ok
    assert result.exit_code is None
    assert result.output is None
    assert not result.timed_out
    assert result.stderr == "missing env: FLEET_TEST_MISSING_A, FLEET_TEST_MISSING_B"
    assert result.duration_s == 0.0


def test_bad_json_appends_stderr(tmp_path: Path) -> None:
    """Unparseable json output keeps exit 0 but appends the reason to stderr."""
    tool = Tool(name="badjson", command=("python3", "-c", "print('not json{')"), output="json")
    result = asyncio.run(
        run_tool(tool, {}, cwd=tmp_path, attempt_dir=tmp_path / "a", environ=_environ())
    )
    assert result.ok
    assert result.output is None
    assert "output:" in result.stderr
    assert (tmp_path / "a" / "stderr.txt").read_text(encoding="utf-8") == result.stderr


def test_args_rendered_into_command(tmp_path: Path) -> None:
    """Given args (with defaults) render into argv without shell splitting."""
    tool = Tool(
        name="greeter",
        command=("python3", "-c", "import sys; print(sys.argv[1])", "{{ args.message }}"),
        args=(ToolArg(name="message", required=True),),
        output="text",
    )
    result = asyncio.run(
        run_tool(
            tool,
            {"message": "hello world"},
            cwd=tmp_path,
            attempt_dir=tmp_path / "a",
            environ=_environ(),
        )
    )
    assert result.ok
    assert result.stdout.strip() == "hello world"


def test_write_step_outputs_dict(tmp_path: Path) -> None:
    """A dict output is written as is."""
    path = write_step_outputs(tmp_path / "step", {"items": [1, 2]})
    assert path == tmp_path / "step" / "outputs" / "outputs.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"items": [1, 2]}


def test_write_step_outputs_list_wrapped(tmp_path: Path) -> None:
    """A lines list (or text) becomes {"result": output}."""
    path = write_step_outputs(tmp_path / "step", ["alpha", "beta"])
    assert json.loads(path.read_text(encoding="utf-8")) == {"result": ["alpha", "beta"]}
    path = write_step_outputs(tmp_path / "other", "raw text")
    assert json.loads(path.read_text(encoding="utf-8")) == {"result": "raw text"}
