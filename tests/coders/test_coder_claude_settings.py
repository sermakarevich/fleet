"""Tests for ClaudeCoder.write_runtime_config (test-after)."""
import json
import stat
from pathlib import Path

import pytest

from fleet.coders.claude import ClaudeCoder

EXPECTED_SETTINGS = (
    Path(__file__).parent.parent / "fixtures" / "expected_settings.json"
)


@pytest.fixture
def coder():
    return ClaudeCoder()


@pytest.fixture
def project(tmp_path):
    """Minimal project root with no pre-existing fleet or claude dirs."""
    return tmp_path


class TestFirstCallWritesSettings:
    def test_settings_json_matches_fixture(self, coder, project):
        coder.write_runtime_config(project, object())
        settings_path = project / ".claude" / "settings.json"
        assert settings_path.exists()
        actual = json.loads(settings_path.read_text())
        expected = json.loads(EXPECTED_SETTINGS.read_text())
        assert actual == expected

    def test_hook_scripts_are_installed(self, coder, project):
        coder.write_runtime_config(project, object())
        hooks_dir = project / ".fleet" / "hooks"
        assert (hooks_dir / "precompact.sh").exists()
        assert (hooks_dir / "pretool_askuserquestion.sh").exists()

    def test_hook_scripts_are_executable(self, coder, project):
        coder.write_runtime_config(project, object())
        for name in ("precompact.sh", "pretool_askuserquestion.sh"):
            script = project / ".fleet" / "hooks" / name
            mode = script.stat().st_mode
            assert mode & stat.S_IXUSR, f"{name} missing user execute bit"
            assert mode & stat.S_IXGRP, f"{name} missing group execute bit"
            assert mode & stat.S_IXOTH, f"{name} missing other execute bit"

    def test_hook_scripts_byte_equal_to_shipped(self, coder, project):
        coder.write_runtime_config(project, object())
        shipped_dir = ClaudeCoder._shipped_hooks_dir()
        for name in ("precompact.sh", "pretool_askuserquestion.sh"):
            installed = project / ".fleet" / "hooks" / name
            shipped = shipped_dir / name
            assert installed.read_bytes() == shipped.read_bytes()


class TestMergeSafety:
    def test_user_owned_hook_entries_survive(self, coder, project):
        """Pre-existing user entries in a different event type are preserved."""
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True)
        user_entry = {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "my-bash-hook.sh"}],
        }
        existing = {"hooks": {"PreToolUse": [user_entry]}}
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2))

        coder.write_runtime_config(project, object())

        settings = json.loads((project / ".claude" / "settings.json").read_text())
        pre_tool_hooks = settings["hooks"]["PreToolUse"]
        user_entries = [e for e in pre_tool_hooks if not e.get("_fleet_managed")]
        assert len(user_entries) == 1
        assert user_entries[0]["matcher"] == "Bash"

    def test_fleet_entry_added_alongside_user_entry(self, coder, project):
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True)
        user_entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": "x.sh"}]}
        existing = {"hooks": {"PreToolUse": [user_entry]}}
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2))

        coder.write_runtime_config(project, object())

        settings = json.loads((project / ".claude" / "settings.json").read_text())
        pre_tool_hooks = settings["hooks"]["PreToolUse"]
        fleet_entries = [e for e in pre_tool_hooks if e.get("_fleet_managed")]
        assert len(fleet_entries) == 1
        assert fleet_entries[0]["matcher"] == "AskUserQuestion"

    def test_unrelated_top_level_settings_preserved(self, coder, project):
        claude_dir = project / ".claude"
        claude_dir.mkdir(parents=True)
        existing = {"model": "claude-opus-4-5", "theme": "dark"}
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2))

        coder.write_runtime_config(project, object())

        settings = json.loads((project / ".claude" / "settings.json").read_text())
        assert settings.get("model") == "claude-opus-4-5"
        assert settings.get("theme") == "dark"


class TestIdempotency:
    def test_second_call_produces_byte_identical_settings(self, coder, project):
        coder.write_runtime_config(project, object())
        first_content = (project / ".claude" / "settings.json").read_bytes()

        coder.write_runtime_config(project, object())
        second_content = (project / ".claude" / "settings.json").read_bytes()

        assert first_content == second_content

    def test_second_call_produces_byte_identical_hook_scripts(self, coder, project):
        coder.write_runtime_config(project, object())
        first = {
            name: (project / ".fleet" / "hooks" / name).read_bytes()
            for name in ("precompact.sh", "pretool_askuserquestion.sh")
        }

        coder.write_runtime_config(project, object())
        second = {
            name: (project / ".fleet" / "hooks" / name).read_bytes()
            for name in ("precompact.sh", "pretool_askuserquestion.sh")
        }

        assert first == second

    def test_fleet_managed_entries_not_duplicated(self, coder, project):
        coder.write_runtime_config(project, object())
        coder.write_runtime_config(project, object())

        settings = json.loads((project / ".claude" / "settings.json").read_text())
        for event_type in ("PreCompact", "PreToolUse"):
            fleet_entries = [
                e for e in settings["hooks"].get(event_type, [])
                if e.get("_fleet_managed")
            ]
            assert len(fleet_entries) == 1, f"{event_type} has duplicated fleet entries"
