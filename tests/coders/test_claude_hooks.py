"""Tests for the claude checkpoint hooks (PostToolUse + PreCompact)."""
from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

from fleet.coders.claude import ClaudeCoder


def _run_hook(script: Path, attempt_dir: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "FLEET_ATTEMPT_DIR": str(attempt_dir), **(extra_env or {})}
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=15)


class TestWriteRuntimeConfigCheckpointHook:
    def test_posttool_checkpoint_hook_installed(self, tmp_path: Path) -> None:
        ClaudeCoder().write_runtime_config(tmp_path, object())
        script = tmp_path / ".fleet" / "hooks" / "posttool_checkpoint.sh"
        assert script.exists()
        mode = script.stat().st_mode
        assert mode & stat.S_IXUSR

    def test_posttool_hook_byte_equal_to_shipped(self, tmp_path: Path) -> None:
        ClaudeCoder().write_runtime_config(tmp_path, object())
        installed = tmp_path / ".fleet" / "hooks" / "posttool_checkpoint.sh"
        shipped = ClaudeCoder._shipped_hooks_dir() / "posttool_checkpoint.sh"
        assert installed.read_bytes() == shipped.read_bytes()

    def test_posttool_entry_in_settings(self, tmp_path: Path) -> None:
        ClaudeCoder().write_runtime_config(tmp_path, object())
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        entries = [e for e in settings["hooks"].get("PostToolUse", []) if e.get("_fleet_managed")]
        assert len(entries) == 1
        assert entries[0]["matcher"] == ""
        assert entries[0]["hooks"][0]["command"] == ".fleet/hooks/posttool_checkpoint.sh"

    def test_posttool_entry_not_duplicated(self, tmp_path: Path) -> None:
        coder = ClaudeCoder()
        coder.write_runtime_config(tmp_path, object())
        coder.write_runtime_config(tmp_path, object())
        settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
        fleet_entries = [
            e for e in settings["hooks"].get("PostToolUse", []) if e.get("_fleet_managed")
        ]
        assert len(fleet_entries) == 1


class TestPosttoolCheckpointScript:
    @staticmethod
    def _script() -> Path:
        return ClaudeCoder._shipped_hooks_dir() / "posttool_checkpoint.sh"

    def test_no_output_without_checkpoint_request(self, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "attempts" / "1"
        attempt_dir.mkdir(parents=True)
        proc = _run_hook(self._script(), attempt_dir)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""
        assert not (attempt_dir / ".checkpoint_sent").exists()

    def test_fires_once_with_valid_json(self, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "attempts" / "1"
        attempt_dir.mkdir(parents=True)
        (attempt_dir / ".checkpoint_requested").touch()

        proc = _run_hook(self._script(), attempt_dir)

        assert proc.returncode == 0
        payload = json.loads(proc.stdout.strip())
        assert (
            payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        )
        assert "HANDOFF.md" in payload["hookSpecificOutput"]["additionalContext"]
        assert (attempt_dir / ".checkpoint_sent").exists()

        second = _run_hook(self._script(), attempt_dir)
        assert second.returncode == 0
        assert second.stdout.strip() == ""

    def test_no_attempt_dir_is_noop(self, tmp_path: Path) -> None:
        import os

        script = self._script()
        env = {k: v for k, v in os.environ.items() if k != "FLEET_ATTEMPT_DIR"}
        env.pop("FLEET_ATTEMPT_DIR", None)
        proc = subprocess.run(
            ["bash", str(script)], capture_output=True, text=True, env=env, timeout=15
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""


class TestPrecompactHook:
    def test_precompact_touches_compacted_marker(self, tmp_path: Path) -> None:
        attempt_dir = tmp_path / "attempts" / "1"
        attempt_dir.mkdir(parents=True)
        script = ClaudeCoder._shipped_hooks_dir() / "precompact.sh"
        proc = _run_hook(script, attempt_dir)
        assert proc.returncode == 0
        assert (attempt_dir / ".compacted").exists()
