import os
import threading
import time
from pathlib import Path

import pytest

from fleet.config import (
    load,
    reload_if_changed,
    write_atomic,
)
from fleet.schemas import RuntimeConfig


def test_load_creates_defaults_when_missing(tmp_path):
    cfg_path = tmp_path / ".fleet" / "runtime.toml"
    assert not cfg_path.exists()

    cfg = load(cfg_path)

    assert cfg_path.exists()
    assert cfg == RuntimeConfig()
    # File should contain the max_concurrent default
    content = cfg_path.read_text()
    assert "max_concurrent" in content


def test_load_partial_toml_overlays_defaults(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    cfg_path.write_text("max_concurrent = 8\n", encoding="utf-8")

    cfg = load(cfg_path)

    assert cfg.max_concurrent == 8
    # Unset fields fall back to defaults
    assert cfg.rate_limit_threshold_pct == 90
    assert cfg.retry_limit == 3
    assert cfg.log_root == "logs"


def test_write_atomic_round_trips_value(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)  # create with defaults

    result = write_atomic(cfg_path, {"max_concurrent": "7"})

    assert result.max_concurrent == 7
    # Reload from disk to confirm persistence
    reloaded = load(cfg_path)
    assert reloaded.max_concurrent == 7


def test_write_atomic_concurrent_writes_produce_valid_toml(tmp_path):
    """Two threads writing different keys; final file is parseable."""
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)

    errors: list[Exception] = []

    def writer_a():
        try:
            for _ in range(10):
                write_atomic(cfg_path, {"max_concurrent": "2"})
                time.sleep(0.001)
        except Exception as exc:
            errors.append(exc)

    def writer_b():
        try:
            for _ in range(10):
                write_atomic(cfg_path, {"retry_limit": "5"})
                time.sleep(0.001)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=writer_a)
    t2 = threading.Thread(target=writer_b)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Concurrent write errors: {errors}"
    # File must still be parseable
    final = load(cfg_path)
    assert isinstance(final, RuntimeConfig)


def test_reload_if_changed_returns_none_when_mtime_unchanged(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)
    stat = os.stat(cfg_path)

    result = reload_if_changed(cfg_path, stat.st_mtime)

    assert result is None


def test_reload_if_changed_returns_snapshot_after_write_atomic(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)
    stat = os.stat(cfg_path)
    old_mtime = stat.st_mtime

    write_atomic(cfg_path, {"max_concurrent": "6"})

    result = reload_if_changed(cfg_path, old_mtime)
    assert result is not None
    new_cfg, new_mtime = result
    assert new_cfg.max_concurrent == 6
    assert new_mtime != old_mtime


def test_write_atomic_unknown_key_raises(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)

    with pytest.raises(ValueError, match="Unknown config key"):
        write_atomic(cfg_path, {"not_a_real_key": "42"})


def test_write_atomic_rejects_config_poll_interval_above_10(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)

    with pytest.raises(ValueError, match="config_poll_interval_sec"):
        write_atomic(cfg_path, {"config_poll_interval_sec": "15"})
