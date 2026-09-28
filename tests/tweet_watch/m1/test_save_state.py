"""Unit under test: fleet.tweet_watch.kb_files.save_state (M1 state saving)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fleet.tweet_watch.kb_files import load_state, save_state


def test_save_creates_missing_parent_dirs(tmp_path: Path) -> None:
    """F12: on save, missing parents (`media/x/` gone) are created (`mkdir -p`)."""
    state_path = tmp_path / "media" / "x" / "watch_state.json"
    save_state(state_path, {"omarsar0": "123"})
    assert load_state(state_path) == {"omarsar0": "123"}


def test_save_round_trips_ids_verbatim(tmp_path: Path) -> None:
    """F9: ids persist verbatim as strings; differing lengths survive a cycle."""
    state_path = tmp_path / "watch_state.json"
    state = {"a": "1", "b": "1942857309483188583"}
    save_state(state_path, state)
    assert load_state(state_path) == state
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert raw == state


def test_save_preserves_handles_no_longer_in_watchlist(tmp_path: Path) -> None:
    """F17: stale entries are written untouched so re-adding a handle never re-emits."""
    state_path = tmp_path / "watch_state.json"
    state = {"omarsar0": "10", "removed_handle": "99"}
    save_state(state_path, state)
    assert load_state(state_path) == state


def test_save_leaves_no_temp_files_behind(tmp_path: Path) -> None:
    """F18: atomic temp-file-plus-rename write; readers never see half-written files."""
    state_path = tmp_path / "watch_state.json"
    save_state(state_path, {"omarsar0": "123"})
    assert sorted(p.name for p in tmp_path.iterdir()) == ["watch_state.json"]
    assert load_state(state_path) == {"omarsar0": "123"}


def test_overwrite_replaces_content_atomically(tmp_path: Path) -> None:
    """F18: last writer wins; the file always holds one complete JSON document."""
    state_path = tmp_path / "watch_state.json"
    save_state(state_path, {"omarsar0": "1"})
    save_state(state_path, {"omarsar0": "2", "typesafeai": "3"})
    assert load_state(state_path) == {"omarsar0": "2", "typesafeai": "3"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["watch_state.json"]


def test_save_failure_raises_naming_state_path_and_keeps_old_content(
    tmp_path: Path,
) -> None:
    """F13: on write failure the error names the state path; state is not advanced."""
    if os.geteuid() == 0:  # root bypasses permission bits
        pytest.skip("permission bits do not apply to root")
    state_path = tmp_path / "watch_state.json"
    save_state(state_path, {"omarsar0": "1"})
    state_path.chmod(0o444)
    try:
        with pytest.raises(OSError) as excinfo:
            save_state(state_path, {"omarsar0": "2"})
    finally:
        state_path.chmod(0o644)
    assert str(state_path) in str(excinfo.value)
    assert load_state(state_path) == {"omarsar0": "1"}
