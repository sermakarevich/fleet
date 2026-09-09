"""Tests for the Agy coder CLI shape (unit under test: coders/agy.py)."""

from pathlib import Path

from fleet.coders import get_coder
from fleet.coders.agy import AgyCoder
from fleet.coders.base import CoderSpec
from fleet.core.task import Task
from fleet.state.paths import fleet_home


def _coder() -> AgyCoder:
    return AgyCoder(fleet_home=fleet_home())


def _task(task_id: str = "test-001") -> Task:
    return Task(id=task_id, title="Test task", description="Do the thing.", status="in_progress")


def test_get_coder_returns_agy_class():
    cls = get_coder("agy")
    assert cls is AgyCoder


def test_agy_spec_names_registry_entry():
    assert isinstance(AgyCoder.spec, CoderSpec)
    assert AgyCoder.spec.name == "agy"
    assert AgyCoder.spec.context_limit == 128_000
    assert AgyCoder.spec.default_model == "GPT-OSS 120B"


def test_build_argv_starts_with_agy_p(tmp_path: Path):
    coder = _coder()
    task = _task()
    argv = coder.build_argv(task, tmp_path)
    assert argv[0] == "agy"
    assert "-p" in argv


def test_build_argv_includes_skip_permissions(tmp_path: Path):
    coder = _coder()
    argv = coder.build_argv(_task(), tmp_path)
    assert "--dangerously-skip-permissions" in argv


def test_default_model_is_gpt_oss_120b():
    """AgyCoder defaults to GPT-OSS 120B per fleet policy."""
    coder = _coder()
    assert coder.model == "GPT-OSS 120B"


def test_uses_custom_model():
    """Constructor accepts an override; the agy CLI itself reads model
    from `~/.gemini/antigravity-cli/settings.json`, so the value is held on
    the coder for supervisor logging and future propagation."""
    coder = AgyCoder(model="GPT-OSS 20B", fleet_home=fleet_home())
    assert coder.model == "GPT-OSS 20B"


def test_build_argv_does_not_pass_model_flag(tmp_path: Path):
    """`agy` rejects `--model` (`flags provided but not defined: -model`),
    so build_argv must not include it."""
    coder = AgyCoder(model="GPT-OSS 120B", fleet_home=fleet_home())
    argv = coder.build_argv(_task(), tmp_path)
    assert "--model" not in argv


def test_build_argv_includes_task_id_in_prompt(tmp_path: Path):
    coder = _coder()
    task = _task("my-task-id")
    argv = coder.build_argv(task, tmp_path)
    prompt = " ".join(argv)
    assert "my-task-id" in prompt


def test_build_argv_inlines_instruction_md_content(tmp_path: Path):
    coder = _coder()
    argv = coder.build_argv(_task(), tmp_path)
    prompt = argv[2]  # final positional arg or prompt argument
    assert "Fleet Task Protocol" in prompt
    assert "Plan before you act" in prompt
    assert "ask_human" in prompt
    assert "fleet bd close" in prompt


def test_env_includes_required_vars(tmp_path: Path):
    coder = _coder()
    task = _task("t-42")
    env = coder.env(task, tmp_path)
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)


def test_normalize_event_returns_none_for_empty_lines():
    coder = _coder()
    assert coder.normalize_event("") is None
    assert coder.normalize_event("   ") is None
    assert coder.normalize_event("\n") is None


def test_normalize_event_plain_text():
    coder = _coder()
    evt = coder.normalize_event("Starting the task...")
    assert evt is not None
    assert evt.kind == "assistant_text"
    assert evt.raw == {"text": "Starting the task..."}


def test_normalize_event_json_assistant():
    coder = _coder()
    raw = (
        '{"type": "assistant", "session_id": "sess_123", '
        '"message": {"usage": {"input_tokens": 100}}}'
    )
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "assistant_text"
    assert evt.session_id == "sess_123"
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 100


def test_normalize_event_json_tool_use():
    coder = _coder()
    raw = '{"type": "tool_use", "name": "Write"}'
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "Write"


def test_normalize_event_json_tool_result():
    coder = _coder()
    raw = '{"type": "tool_result", "name": "Write"}'
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "tool_result"
    assert evt.tool_name == "Write"


def test_normalize_event_json_session_ended():
    coder = _coder()
    raw = '{"type": "result", "session_id": "sess_123", "usage": {"input_tokens": 500}}'
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "session_ended"
    assert evt.session_id == "sess_123"
    assert evt.usage == {"input_tokens": 500}
