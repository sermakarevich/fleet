"""Tests for the Claude coder CLI shape (unit under test: coders/claude.py argv, env, registry)."""

import json
from pathlib import Path

import pytest

import fleet.coders.base as coder_mod
import fleet.coders.claude as cli_mod
import fleet.core.task as task_mod
from fleet.coders import get_coder
from fleet.coders.base import CoderSpec
from fleet.coders.claude import ClaudeCoder
from fleet.coders.mcp import write_mcp_config
from fleet.core.task import Task
from fleet.integrations.mcp_servers import fleet_mcp_servers
from fleet.state.paths import fleet_home
from tests.coders.conftest import _coder


def _task(task_id: str = "test-001") -> Task:
    return Task(id=task_id, title="Test task", description="Do the thing.", status="in_progress")


def test_get_coder_returns_claude_class():
    cls = get_coder("claude")
    assert cls is ClaudeCoder


def test_get_coder_unknown_raises():
    with pytest.raises(ValueError, match="Unknown coder"):
        get_coder("unknown_cli")


def test_claude_spec_names_registry_entry():
    assert isinstance(ClaudeCoder.spec, CoderSpec)
    assert ClaudeCoder.spec.name == "claude"
    assert ClaudeCoder.spec.context_limit == 200_000
    assert ClaudeCoder.spec.default_model == "sonnet"


def test_build_argv_starts_with_claude_p(tmp_path: Path):
    coder = _coder()
    task = _task()
    argv = coder.build_argv(task, tmp_path)
    assert argv[0] == "claude"
    assert "-p" in argv


def test_build_argv_includes_stream_json_output(tmp_path: Path):
    coder = _coder()
    argv = coder.build_argv(_task(), tmp_path)
    idx = argv.index("--output-format")
    assert argv[idx + 1] == "stream-json"


def test_build_argv_includes_verbose_flag(tmp_path: Path):
    """claude -p with --output-format stream-json requires --verbose."""
    coder = _coder()
    argv = coder.build_argv(_task(), tmp_path)
    assert "--verbose" in argv


def test_build_argv_defaults_to_sonnet_model(tmp_path: Path):
    coder = _coder()
    argv = coder.build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "sonnet"


def test_build_argv_uses_custom_model(tmp_path: Path):
    coder = ClaudeCoder(model="opus", fleet_home=fleet_home())
    argv = coder.build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "opus"


def test_build_argv_includes_task_id_in_prompt(tmp_path: Path):
    coder = _coder()
    task = _task("my-task-id")
    argv = coder.build_argv(task, tmp_path)
    prompt = " ".join(argv)
    assert "my-task-id" in prompt


def test_build_argv_inlines_instruction_md_content(tmp_path: Path):
    """The full INSTRUCTION.md protocol text must be inlined into the prompt."""
    coder = _coder()
    argv = coder.build_argv(_task(), tmp_path)
    prompt = argv[-1]  # final positional arg is the prompt
    # Spot-check several distinctive phrases from the bundled INSTRUCTION.md.
    assert "Fleet Task Protocol" in prompt
    assert "Plan before you act" in prompt
    assert "ask_human" in prompt
    assert "fleet bd close" in prompt


def test_build_argv_includes_invocation_directory_when_task_cwd_set(tmp_path: Path):
    coder = _coder()
    task = Task(
        id="t-cwd",
        title="t",
        description="d",
        status="open",
        cwd="/Users/me/project-x",
    )
    argv = coder.build_argv(task, tmp_path)
    prompt = argv[-1]
    assert "Invocation directory: /Users/me/project-x" in prompt


def test_build_argv_omits_invocation_line_when_task_cwd_missing(tmp_path: Path):
    coder = _coder()
    task = Task(id="t-no-cwd", title="t", description="d", status="open", cwd=None)
    argv = coder.build_argv(task, tmp_path)
    prompt = argv[-1]
    assert "Invocation directory:" not in prompt


def test_build_argv_does_not_reference_external_protocol_file(tmp_path: Path):
    """Prompt must not tell the coder to go read CLAUDE.md / AGENTS.md."""
    coder = _coder()
    argv = coder.build_argv(_task(), tmp_path)
    prompt = argv[-1]
    assert "Follow the Loop Task Protocol in CLAUDE.md" not in prompt
    assert "AGENTS.md" not in prompt


def test_env_includes_required_vars(tmp_path: Path):
    coder = _coder()
    task = _task("t-42")
    env = coder.env(task, tmp_path)
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)


def test_env_does_not_contain_api_key(tmp_path: Path):
    coder = _coder()
    env = coder.env(_task(), tmp_path)
    assert "ANTHROPIC_API_KEY" not in env


def test_env_does_not_include_fleet_attempt(tmp_path: Path):
    coder = _coder()
    env = coder.env(_task(), tmp_path)
    assert "FLEET_ATTEMPT" not in env


def test_build_argv_with_worktree_marker_includes_isolation_protocol(tmp_path: Path):
    """When a .worktree marker exists, the prompt must contain the isolation block."""
    (tmp_path / ".worktree").touch()
    coder = _coder()
    task = _task("wt-001")
    argv = coder.build_argv(task, tmp_path)
    prompt = argv[-1]
    assert "Do NOT run `fleet bd close`" in prompt


def test_build_argv_without_worktree_marker_excludes_isolation_protocol(tmp_path: Path):
    """Without a .worktree marker, the prompt must NOT contain the isolation block."""
    coder = _coder()
    task = _task()
    argv = coder.build_argv(task, tmp_path)
    prompt = argv[-1]
    assert "Do NOT run `fleet bd close`" not in prompt


def test_no_anthropic_import_in_coder_module():

    for mod in (coder_mod, cli_mod, task_mod):
        src = Path(mod.__file__).read_text()
        assert "anthropic" not in src, f"anthropic import found in {mod.__file__}"
        assert "claude-agent-sdk" not in src, f"agent-sdk import found in {mod.__file__}"


def test_build_argv_includes_mcp_config_pointing_at_file_with_ask_human(
    tmp_path: Path,
):
    argv = _coder().build_argv(_task(), tmp_path)
    assert "--mcp-config" in argv
    assert "--strict-mcp-config" in argv
    cfg_path = Path(argv[argv.index("--mcp-config") + 1])
    assert cfg_path.exists()
    payload = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "ask_human" in payload["mcpServers"]
    assert "web_fetch" in payload["mcpServers"]


def test_write_mcp_config_matches_shared_definitions(tmp_path: Path):

    fleet_home = tmp_path / "fleet_home"
    cfg_path = write_mcp_config(tmp_path / "attempt", fleet_mcp_servers(fleet_home))
    payload = json.loads(cfg_path.read_text(encoding="utf-8"))
    shared = fleet_mcp_servers(fleet_home)
    for name, entry in shared.items():
        assert payload["mcpServers"][name]["command"] == entry["command"]
        assert payload["mcpServers"][name]["args"] == entry["args"]
        assert payload["mcpServers"][name]["env"] == entry["env"]
