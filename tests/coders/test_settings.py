"""Env-derived coder settings: the one place that reads coder env vars."""

from pathlib import Path

from fleet.coders.settings import (
    default_agent_dir,
    default_log_file,
    settings_from_env,
)


def test_defaults_are_home_based(monkeypatch):
    monkeypatch.delenv("OPENCODE_LOG_FILE", raising=False)
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    env = settings_from_env({})
    assert env.opencode_log_file == default_log_file()
    assert env.pi_agent_dir == default_agent_dir()
    assert env.opencode_log_file == (
        Path.home() / ".local" / "share" / "opencode" / "log" / "opencode.log"
    )
    assert env.pi_agent_dir == Path.home() / ".pi" / "agent"


def test_opencode_log_file_override(tmp_path: Path):
    custom = tmp_path / "opencode.log"
    env = settings_from_env({"OPENCODE_LOG_FILE": str(custom)})
    assert env.opencode_log_file == custom


def test_pi_agent_dir_override(tmp_path: Path):
    custom = tmp_path / "agent"
    env = settings_from_env({"PI_CODING_AGENT_DIR": str(custom)})
    assert env.pi_agent_dir == custom


def test_blank_values_fall_back_to_defaults():
    env = settings_from_env({"OPENCODE_LOG_FILE": "", "PI_CODING_AGENT_DIR": ""})
    assert env.opencode_log_file == default_log_file()
    assert env.pi_agent_dir == default_agent_dir()
