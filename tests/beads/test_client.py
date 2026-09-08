from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet.beads import client as beads_client
from fleet.beads.client import BeadsError


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
        pytest.raises(BeadsError, match="not found"),
    ):
        beads_client.run(["show", "nope"], cwd=tmp_path)


def test_run_check_false_does_not_raise(tmp_path: Path) -> None:
    failed = subprocess.CompletedProcess(
        args=["bd", "show", "nope"], returncode=1, stdout="", stderr="not found"
    )
    with patch("fleet.beads.client.subprocess.run", return_value=failed):
        result = beads_client.run(["show", "nope"], cwd=tmp_path, check=False)
    assert result.returncode == 1
