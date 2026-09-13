"""Tests for the bd CLI client (unit under test: beads/client.py)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet.beads import client as beads_client
from fleet.beads.client import BdError


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["bd"], returncode=returncode, stdout=stdout, stderr="")


def test_run_json_unwraps_bare_list(tmp_path: Path) -> None:
    with patch(
        "fleet.beads.client.subprocess.run",
        return_value=_completed('[{"id": "fleet-1"}]'),
    ):
        result = beads_client.run_json(["list"], cwd=tmp_path)
    assert result == [{"id": "fleet-1"}]


def test_run_json_unwraps_data_envelope(tmp_path: Path) -> None:
    with patch(
        "fleet.beads.client.subprocess.run",
        return_value=_completed('{"data": [{"id": "fleet-1"}]}'),
    ):
        result = beads_client.run_json(["list"], cwd=tmp_path)
    assert result == [{"id": "fleet-1"}]


def test_run_json_returns_none_on_empty_stdout(tmp_path: Path) -> None:
    with patch("fleet.beads.client.subprocess.run", return_value=_completed("")):
        result = beads_client.run_json(["list"], cwd=tmp_path)
    assert result is None


def test_beads_error_on_nonzero_rc(tmp_path: Path) -> None:
    failed = subprocess.CompletedProcess(
        args=["bd", "show", "nope"], returncode=1, stdout="", stderr="not found"
    )
    with (
        patch("fleet.beads.client.subprocess.run", return_value=failed),
        pytest.raises(BdError, match="not found"),
    ):
        beads_client.run_bd(["show", "nope"], cwd=tmp_path)


def test_try_run_bd_does_not_raise(tmp_path: Path) -> None:
    failed = subprocess.CompletedProcess(
        args=["bd", "show", "nope"], returncode=1, stdout="", stderr="not found"
    )
    with patch("fleet.beads.client.subprocess.run", return_value=failed):
        result = beads_client.try_run_bd(["show", "nope"], cwd=tmp_path)
    assert result.returncode == 1


def test_run_raises_bd_error_on_timeout(tmp_path: Path) -> None:
    """A hung `bd` fails fast as BdError instead of hanging the supervisor."""
    with (
        patch(
            "fleet.beads.client.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["bd", "list"], 60),
        ),
        pytest.raises(BdError, match="timed out"),
    ):
        beads_client.run_bd(["list"], cwd=tmp_path, timeout=1)


def test_bd_client_run_json_carries_timeout_and_actor(tmp_path: Path) -> None:
    """BdClient owns the timeout and sets BEADS_ACTOR for attributed claims."""
    seen: dict = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        seen.update(kwargs)
        return _completed("[]")

    client = beads_client.BdClient(tmp_path, timeout=7)
    with patch("fleet.beads.client.subprocess.run", side_effect=fake_run):
        assert client.run_json(["list"], actor="worker-1") == []
    assert seen["timeout"] == 7
    assert seen["env"]["BEADS_ACTOR"] == "worker-1"


def test_bd_client_run_timeout_overrides_default(tmp_path: Path) -> None:
    """A per-call timeout overrides the client default."""
    seen: dict = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        seen.update(kwargs)
        return _completed("")

    client = beads_client.BdClient(tmp_path, timeout=60)
    with patch("fleet.beads.client.subprocess.run", side_effect=fake_run):
        client.run(["show", "t-1"], timeout=5)
    assert seen["timeout"] == 5


def test_resolve_bd_bin_prefers_env_override(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """FLEET_BD_BIN wins even when PATH has no `bd`."""
    fake_bd = tmp_path / "bd"
    fake_bd.write_text("#!/bin/sh\necho hi\n")
    fake_bd.chmod(0o755)
    monkeypatch.setenv("FLEET_BD_BIN", str(fake_bd))
    monkeypatch.setenv("PATH", "")
    assert beads_client.resolve_bd_bin() == str(fake_bd)


def test_resolve_bd_bin_uses_fallback_when_path_empty(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With an empty PATH, an existing fallback candidate is used."""
    fake_home = tmp_path / "home"
    local_bin = fake_home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    fake_bd = local_bin / "bd"
    fake_bd.write_text("#!/bin/sh\necho hi\n")
    fake_bd.chmod(0o755)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("FLEET_BD_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    assert beads_client.resolve_bd_bin() == str(fake_bd)


def test_resolve_bd_bin_missing_lists_candidates(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Nothing found -> BdError naming every place that was checked."""
    monkeypatch.delenv("FLEET_BD_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("HOME", "/nonexistent-home-for-bd-test")
    with (
        patch.object(beads_client, "bd_binary_candidates", return_value=["/nope/bd"]),
        pytest.raises(BdError, match="/nope/bd"),
    ):
        beads_client.resolve_bd_bin()


def test_try_run_bd_uses_resolved_binary(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """try_run_bd execs the resolved absolute path, not bare `bd`."""
    fake_bd = tmp_path / "bd"
    fake_bd.write_text("#!/bin/sh\necho hi\n")
    fake_bd.chmod(0o755)
    monkeypatch.setenv("FLEET_BD_BIN", str(fake_bd))
    seen: dict = {}
    seen_cmd: list = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        seen_cmd.extend(cmd)
        seen.update(kwargs)
        return _completed("")

    with patch("fleet.beads.client.subprocess.run", side_effect=fake_run):
        beads_client.try_run_bd(["--version"], cwd=tmp_path)
    assert seen_cmd[0] == str(fake_bd)
