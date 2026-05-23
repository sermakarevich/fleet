import json
from pathlib import Path

import pytest

from fleet.coder import Coder
from fleet.coders import get_coder
from fleet.coders.claude import ClaudeCoder
from fleet.schemas import Task


FIXTURES = Path(__file__).parent / "fixtures"


def _coder() -> ClaudeCoder:
    return ClaudeCoder()


def _task(task_id: str = "test-001") -> Task:
    return Task(id=task_id, title="Test task", description="Do the thing.", status="in_progress")


def _lines(fixture: str) -> list[str]:
    return [
        line for line in (FIXTURES / fixture).read_text().splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_get_coder_returns_claude_class():
    cls = get_coder("claude")
    assert cls is ClaudeCoder


def test_get_coder_unknown_raises():
    with pytest.raises(ValueError, match="Unknown coder"):
        get_coder("unknown_cli")


def test_claude_coder_is_subclass_of_coder_base():
    assert issubclass(ClaudeCoder, Coder)


# ---------------------------------------------------------------------------
# build_argv — FR-10
# ---------------------------------------------------------------------------

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
    coder = ClaudeCoder(model="opus")
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
    assert "On every fresh start" in prompt
    assert "Q&A.md" in prompt
    assert "bd update" in prompt


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


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------

def test_env_includes_required_vars(tmp_path: Path):
    coder = _coder()
    task = _task("t-42")
    env = coder.env(task, tmp_path)
    assert env["FLEET_TASK_ID"] == "t-42"
    assert env["FLEET_TASK_DIR"] == str(tmp_path)
    assert env["FLEET_ARTIFACT_DIR"] == str(tmp_path / "artifacts")


def test_env_does_not_contain_api_key(tmp_path: Path):
    coder = _coder()
    env = coder.env(_task(), tmp_path)
    assert "ANTHROPIC_API_KEY" not in env


def test_env_does_not_include_fleet_attempt(tmp_path: Path):
    coder = _coder()
    env = coder.env(_task(), tmp_path)
    assert "FLEET_ATTEMPT" not in env


# ---------------------------------------------------------------------------
# normalize_event — malformed input
# ---------------------------------------------------------------------------

def test_normalize_event_returns_none_for_malformed_json():
    coder = _coder()
    assert coder.normalize_event("not json") is None
    assert coder.normalize_event("") is None
    assert coder.normalize_event("{bad") is None


def test_normalize_event_returns_none_for_non_dict():
    coder = _coder()
    assert coder.normalize_event("[1,2,3]") is None


def test_normalize_event_returns_none_for_unknown_type():
    coder = _coder()
    assert coder.normalize_event('{"type": "completely_unknown_type"}') is None


# ---------------------------------------------------------------------------
# normalize_event — assistant_text
# ---------------------------------------------------------------------------

def test_normalize_assistant_text():
    coder = _coder()
    [line] = _lines("claude_stream_basic.jsonl")[:1]
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "assistant_text"
    assert evt.session_id == "sess_abc123"
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 100


# ---------------------------------------------------------------------------
# normalize_event — tool_use
# ---------------------------------------------------------------------------

def test_normalize_tool_use():
    coder = _coder()
    lines = _lines("claude_stream_basic.jsonl")
    # second line is tool_use
    evt = coder.normalize_event(lines[1])
    assert evt is not None
    assert evt.kind == "tool_use"
    assert evt.tool_name == "Read"


# ---------------------------------------------------------------------------
# normalize_event — tool_result
# ---------------------------------------------------------------------------

def test_normalize_tool_result():
    coder = _coder()
    lines = _lines("claude_stream_basic.jsonl")
    # third line is tool_result
    evt = coder.normalize_event(lines[2])
    assert evt is not None
    assert evt.kind == "tool_result"
    assert evt.tool_name == "Read"


# ---------------------------------------------------------------------------
# normalize_event — session_started / session_ended
# ---------------------------------------------------------------------------

def test_normalize_session_started():
    coder = _coder()
    [init_line, _result_line] = _lines("claude_stream_session.jsonl")
    evt = coder.normalize_event(init_line)
    assert evt is not None
    assert evt.kind == "session_started"
    assert evt.session_id == "sess_xyz789"


def test_normalize_session_ended():
    coder = _coder()
    [_init_line, result_line] = _lines("claude_stream_session.jsonl")
    evt = coder.normalize_event(result_line)
    assert evt is not None
    assert evt.kind == "session_ended"
    assert evt.session_id == "sess_xyz789"
    assert evt.usage is not None
    assert evt.usage["input_tokens"] == 2500


# ---------------------------------------------------------------------------
# normalize_event — rate_limit_info (FR-19 soft path)
# ---------------------------------------------------------------------------

def test_normalize_rate_limit_info():
    coder = _coder()
    [line] = _lines("claude_stream_rate_limit_info.jsonl")
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "rate_limit_info"
    assert evt.rate_info is not None
    assert evt.rate_info["usage_pct"] == pytest.approx(85.5)
    assert evt.rate_info["resets_at"] == 1748001000
    assert evt.rate_info["status"] == "approaching"


def test_normalize_rate_limit_info_utilization_fraction():
    """Real Claude CLI reports usage via `utilization` (0-1 fraction)."""
    coder = _coder()
    [line] = _lines("claude_stream_rate_limit_utilization.jsonl")
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "rate_limit_info"
    assert evt.rate_info is not None
    assert evt.rate_info["usage_pct"] == pytest.approx(90.0)
    assert evt.rate_info["resets_at"] == 1779564600
    assert evt.rate_info["status"] == "allowed_warning"


def test_normalize_rate_limit_info_utilization_overage_above_one():
    """`utilization` can exceed 1.0 during overage; gauge must accept it."""
    coder = _coder()
    raw = json.dumps({
        "type": "rate_limit_event",
        "rate_limit_info": {
            "status": "allowed_warning",
            "utilization": 1.07,
            "rateLimitType": "overage",
            "resetsAt": 1779564600,
        },
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.rate_info is not None
    assert evt.rate_info["usage_pct"] == pytest.approx(107.0)


def test_normalize_rate_limit_info_missing_usage_fields():
    """No usage_pct, usagePct, or utilization -> rate_info['usage_pct'] is None."""
    coder = _coder()
    raw = json.dumps({
        "type": "rate_limit_event",
        "rate_limit_info": {"status": "allowed", "resetsAt": 1779564600},
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.rate_info is not None
    assert evt.rate_info["usage_pct"] is None
    assert evt.rate_info["resets_at"] == 1779564600


# ---------------------------------------------------------------------------
# normalize_event — rate_limit (FR-19 hard rejection)
# ---------------------------------------------------------------------------

def test_normalize_rate_limit_rejected():
    coder = _coder()
    [line] = _lines("claude_stream_rate_limit_rejected.jsonl")
    evt = coder.normalize_event(line)
    assert evt is not None
    assert evt.kind == "rate_limit"
    assert evt.rate_info is not None
    assert evt.rate_info["status"] == "rejected"
    assert evt.rate_info["resets_at"] == 1748001600


# ---------------------------------------------------------------------------
# normalize_event — thinking blocks
# ---------------------------------------------------------------------------

def test_normalize_thinking_event():
    coder = _coder()
    raw = json.dumps({
        "type": "assistant",
        "message": {
            "content": [{"type": "thinking", "thinking": "Let me reason..."}],
            "usage": {"input_tokens": 50, "output_tokens": 30},
        },
        "session_id": "sess_think",
    })
    evt = coder.normalize_event(raw)
    assert evt is not None
    assert evt.kind == "thinking"
    assert evt.session_id == "sess_think"


# ---------------------------------------------------------------------------
# No anthropic / claude-agent-sdk imports in coder files (FR-33, FR-35)
# ---------------------------------------------------------------------------

def test_no_anthropic_import_in_coder_module():
    import fleet.coder as coder_mod
    import fleet.coders.claude as cli_mod
    import fleet.schemas as schemas_mod

    for mod in (coder_mod, cli_mod, schemas_mod):
        src = Path(mod.__file__).read_text()
        assert "anthropic" not in src, f"anthropic import found in {mod.__file__}"
        assert "claude-agent-sdk" not in src, f"agent-sdk import found in {mod.__file__}"
