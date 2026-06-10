import json
from pathlib import Path

from fleet.coders.base import Coder
from fleet.coders import get_coder
from fleet.coders.codex import CodexCoder
from fleet.schemas import Task


def _coder() -> CodexCoder:
    return CodexCoder()


def _task(task_id: str = "test-001") -> Task:
    return Task(id=task_id, title="Test task", description="Do the thing.", status="in_progress")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_get_coder_returns_codex_class():
    cls = get_coder("codex")
    assert cls is CodexCoder


def test_codex_coder_is_subclass_of_coder_base():
    assert issubclass(CodexCoder, Coder)


# ---------------------------------------------------------------------------
# build_argv
# ---------------------------------------------------------------------------

def test_build_argv_starts_with_codex_exec(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert argv[0] == "codex"
    assert argv[1] == "exec"


def test_build_argv_includes_json_flag(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert "--json" in argv


def test_build_argv_includes_bypass_approvals_flag(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    assert "--dangerously-bypass-approvals-and-sandbox" in argv


def test_build_argv_includes_model_flag_defaults_to_o4_mini(tmp_path: Path):
    argv = _coder().build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "o4-mini"


def test_build_argv_uses_custom_model(tmp_path: Path):
    argv = CodexCoder(model="o3").build_argv(_task(), tmp_path)
    idx = argv.index("--model")
    assert argv[idx + 1] == "o3"


def test_default_model_attribute_is_o4_mini():
    assert _coder().model == "o4-mini"


def test_build_argv_includes_task_id_in_prompt(tmp_path: Path):
    argv = _coder().build_argv(_task("my-task-id"), tmp_path)
    assert "my-task-id" in " ".join(argv)


def test_build_argv_inlines_instruction_md_content(tmp_path: Path):
    prompt = _coder().build_argv(_task(), tmp_path)[-1]
    assert "Fleet Task Protocol" in prompt
    assert "On every fresh start" in prompt
    assert "ask_human" in prompt
    assert "bd update" in prompt


def test_build_argv_includes_cd_flag_when_task_has_cwd(tmp_path: Path):
    task = Task(id="t-cwd", title="t", description="d", status="open", cwd="/Users/me/project")
    argv = _coder().build_argv(task, tmp_path)
    idx = argv.index("--cd")
    assert argv[idx + 1] == "/Users/me/project"


def test_build_argv_omits_cd_flag_when_no_cwd(tmp_path: Path):
    task = Task(id="t-no-cwd", title="t", description="d", status="open", cwd=None)
    argv = _coder().build_argv(task, tmp_path)
    assert "--cd" not in argv


def test_build_argv_includes_invocation_directory_when_task_cwd_set(tmp_path: Path):
    task = Task(id="t-cwd", title="t", description="d", status="open", cwd="/Users/me/project-x")
    prompt = _coder().build_argv(task, tmp_path)[-1]
    assert "Invocation directory: /Users/me/project-x" in prompt


def test_build_argv_omits_invocation_line_when_no_cwd(tmp_path: Path):
    task = Task(id="t-no-cwd", title="t", description="d", status="open", cwd=None)
    prompt = _coder().build_argv(task, tmp_path)[-1]
    assert "Invocation directory:" not in prompt


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------

def test_env_includes_required_vars(tmp_path: Path):
    env = _coder().env(_task("t-42"), tmp_path)
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)
    assert env["FLEET_ARTIFACT_DIR"] == str(tmp_path / "artifacts")


# ---------------------------------------------------------------------------
# normalize_event — malformed / unknown
# ---------------------------------------------------------------------------

def test_normalize_event_returns_none_for_empty_lines():
    coder = _coder()
    assert coder.normalize_event("") is None
    assert coder.normalize_event("   ") is None
    assert coder.normalize_event("\n") is None


def test_normalize_event_returns_none_for_malformed_json():
    coder = _coder()
    assert coder.normalize_event("not json") is None
    assert coder.normalize_event("{bad") is None


def test_normalize_event_returns_none_for_non_dict():
    coder = _coder()
    assert coder.normalize_event("[1,2,3]") is None


def test_normalize_event_returns_none_for_unknown_type():
    coder = _coder()
    assert coder.normalize_event('{"type": "completely_unknown"}') is None


def test_normalize_turn_started_returns_none():
    coder = _coder()
    assert coder.normalize_event('{"type": "turn.started"}') is None


# ---------------------------------------------------------------------------
# normalize_event — thread.started → session_started
# ---------------------------------------------------------------------------

def test_normalize_thread_started():
    coder = _coder()
    raw = json.dumps({"type": "thread.started", "thread_id": "thread-abc123"})
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "session_started"
    assert evt.session_id == "thread-abc123"


# ---------------------------------------------------------------------------
# normalize_event — turn.completed → session_ended
# ---------------------------------------------------------------------------

def test_normalize_turn_completed():
    coder = _coder()
    raw = json.dumps({
        "type": "turn.completed",
        "usage": {
            "input_tokens": 500,
            "cached_input_tokens": 100,
            "output_tokens": 200,
            "reasoning_output_tokens": 50,
        },
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "session_ended"
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 500
    assert evt.usage["cached_input_tokens"] == 100


def test_normalize_turn_completed_no_usage():
    coder = _coder()
    raw = json.dumps({"type": "turn.completed"})
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "session_ended"
    assert evt.usage is None


# ---------------------------------------------------------------------------
# normalize_event — turn.failed / error → error
# ---------------------------------------------------------------------------

def test_normalize_turn_failed():
    coder = _coder()
    raw = json.dumps({"type": "turn.failed", "error": {"message": "model error"}})
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "error"


def test_normalize_error_event():
    coder = _coder()
    raw = json.dumps({"type": "error", "message": "fatal error"})
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "error"


# ---------------------------------------------------------------------------
# normalize_event — agent_message
# ---------------------------------------------------------------------------

def test_normalize_agent_message_completed_is_assistant_text():
    coder = _coder()
    raw = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_0", "type": "agent_message", "text": "Done!"},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "assistant_text"


def test_normalize_agent_message_started_returns_none():
    coder = _coder()
    raw = json.dumps({
        "type": "item.started",
        "item": {"id": "item_0", "type": "agent_message", "text": ""},
    })
    assert coder.normalize_event(raw) is None


def test_normalize_agent_message_updated_returns_none():
    coder = _coder()
    raw = json.dumps({
        "type": "item.updated",
        "item": {"id": "item_0", "type": "agent_message", "text": "partial"},
    })
    assert coder.normalize_event(raw) is None


# ---------------------------------------------------------------------------
# normalize_event — reasoning → thinking
# ---------------------------------------------------------------------------

def test_normalize_reasoning_completed_is_thinking():
    coder = _coder()
    raw = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_1", "type": "reasoning", "text": "Let me think..."},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "thinking"


def test_normalize_reasoning_started_returns_none():
    coder = _coder()
    raw = json.dumps({
        "type": "item.started",
        "item": {"id": "item_1", "type": "reasoning", "text": ""},
    })
    assert coder.normalize_event(raw) is None


# ---------------------------------------------------------------------------
# normalize_event — tool item types
# ---------------------------------------------------------------------------

def test_normalize_command_execution_started_is_tool_use():
    coder = _coder()
    raw = json.dumps({
        "type": "item.started",
        "item": {"id": "item_2", "type": "command_execution", "command": "ls"},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "command_execution"


def test_normalize_command_execution_completed_is_tool_result():
    coder = _coder()
    raw = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_2", "type": "command_execution", "exit_code": 0},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "tool_result"
    assert evt.tool_name == "command_execution"


def test_normalize_command_execution_updated_returns_none():
    coder = _coder()
    raw = json.dumps({
        "type": "item.updated",
        "item": {"id": "item_2", "type": "command_execution"},
    })
    assert coder.normalize_event(raw) is None


def test_normalize_file_change_started_is_tool_use():
    coder = _coder()
    raw = json.dumps({
        "type": "item.started",
        "item": {"id": "item_3", "type": "file_change"},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "file_change"


def test_normalize_file_change_completed_is_tool_result():
    coder = _coder()
    raw = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_3", "type": "file_change"},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "tool_result"
    assert evt.tool_name == "file_change"


def test_normalize_mcp_tool_call_started_is_tool_use():
    coder = _coder()
    raw = json.dumps({
        "type": "item.started",
        "item": {"id": "item_4", "type": "mcp_tool_call"},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "mcp_tool_call"


def test_normalize_web_search_started_is_tool_use():
    coder = _coder()
    raw = json.dumps({
        "type": "item.started",
        "item": {"id": "item_5", "type": "web_search"},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "web_search"


def test_normalize_todo_list_returns_none():
    """todo_list is an agent-internal planning artifact, not a fleet event."""
    coder = _coder()
    raw = json.dumps({
        "type": "item.completed",
        "item": {"id": "item_6", "type": "todo_list"},
    })
    assert coder.normalize_event(raw) is None
