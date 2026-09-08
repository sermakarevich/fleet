import logging
import os
import threading
import time

import pytest

from fleet.core.config import (
    RuntimeConfig,
    load,
    reload_if_changed,
    write_atomic,
)


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
    # Unset fields fall back to defaults — now represented as module constants
    # (rate_limit_threshold_pct and retry_limit are no longer RuntimeConfig fields)


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
                write_atomic(cfg_path, {"stall_warning_minutes": "85"})
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


def test_write_atomic_unknown_coder_raises(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)

    with pytest.raises(ValueError, match="Unknown coder"):
        write_atomic(cfg_path, {"coder": "garbage_typo"})

    # File on disk must not have been mutated.
    reloaded = load(cfg_path)
    assert reloaded.coder == RuntimeConfig().coder


def test_write_atomic_valid_coder_round_trips(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)

    result = write_atomic(cfg_path, {"coder": "codex"})
    assert result.coder == "codex"
    assert load(cfg_path).coder == "codex"


def test_write_atomic_context_windows_round_trips(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    load(cfg_path)

    result = write_atomic(
        cfg_path,
        {
            "context_windows": "muse-spark-1.3-contributor:1048576",
            "opencode_default_model": "qwen3.6:latest",
        },
    )
    assert result.context_windows == "muse-spark-1.3-contributor:1048576"
    assert result.opencode_default_model == "qwen3.6:latest"
    reloaded = load(cfg_path)
    assert reloaded.context_windows == "muse-spark-1.3-contributor:1048576"
    assert reloaded.opencode_default_model == "qwen3.6:latest"


def test_load_picks_up_context_windows_from_toml(tmp_path):
    cfg_path = tmp_path / "runtime.toml"
    cfg_path.write_text(
        """context_windows = "muse-spark-1.3-contributor:1048576"
opencode_default_model = "qwen3.6:latest"
""",
        encoding="utf-8",
    )

    cfg = load(cfg_path)

    assert cfg.context_windows == "muse-spark-1.3-contributor:1048576"
    assert cfg.opencode_default_model == "qwen3.6:latest"


def test_deprecated_context_keys_are_ignored_with_warning(tmp_path, caplog):
    """Old single-number keys no longer exist; they warn and fall back to defaults."""

    cfg_path = tmp_path / "runtime.toml"
    cfg_path.write_text(
        """opencode_context_limit = 64000
opencode_bedrock_context_limit = 300000
""",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger="fleet.core.config"):
        cfg = load(cfg_path)

    assert cfg.context_windows == ""
    assert any("opencode_context_limit" in r.message for r in caplog.records)


def test_bedrock_config_defaults():
    cfg = RuntimeConfig()
    assert cfg.opencode_bedrock_region == ""
    assert cfg.opencode_bedrock_profile == ""
    assert cfg.context_windows == ""
