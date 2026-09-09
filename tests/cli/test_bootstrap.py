"""Tests for cli.bootstrap: the one place commands get their dependencies."""

from __future__ import annotations

from pathlib import Path

from fleet.beads.queue import BeadsQueue
from fleet.cli import bootstrap
from fleet.core.config import RuntimeConfig


def test_home_respects_fleet_home_env(tmp_path: Path, monkeypatch) -> None:
    """fleet_home() resolves $FLEET_HOME."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    assert bootstrap.fleet_home() == tmp_path.resolve()


def test_log_dir_joins_relative_root(tmp_path: Path, monkeypatch) -> None:
    """A relative LOG_ROOT resolves under the fleet fleet_home."""
    monkeypatch.setattr(bootstrap, "LOG_ROOT", "logging")
    assert bootstrap.log_dir(tmp_path) == tmp_path / "logging"


def test_log_dir_keeps_absolute_root(tmp_path: Path, monkeypatch) -> None:
    """An absolute LOG_ROOT passes through untouched."""
    monkeypatch.setattr(bootstrap, "LOG_ROOT", "/var/log/fleet")
    assert bootstrap.log_dir(tmp_path) == Path("/var/log/fleet")


def test_queue_bound_to_home(tmp_path: Path) -> None:
    """queue() builds a BeadsQueue rooted at the given fleet_home."""
    q = bootstrap.queue(tmp_path)
    assert isinstance(q, BeadsQueue)
    assert q.repo_root == tmp_path


def test_config_creates_defaults_when_missing(tmp_path: Path) -> None:
    """config() writes runtime.toml with defaults on first read."""
    cfg = bootstrap.config(tmp_path)
    assert isinstance(cfg, RuntimeConfig)
    assert cfg.coder == RuntimeConfig().coder
    assert (tmp_path / "runtime.toml").exists()
