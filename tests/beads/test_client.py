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
