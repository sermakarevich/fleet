"""Unit under test: fleet.tweet_watch.kb_files.load_state (M1 state loading)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet.tweet_watch.kb_files import load_state


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_state_file_reads_as_empty_dict(tmp_path: Path) -> None:
    """Missing state file reads as `{}` (F12 read side)."""
    assert load_state(tmp_path / "watch_state.json") == {}


def test_valid_state_round_trips_ids_verbatim_as_strings(tmp_path: Path) -> None:
    """F9: snowflake ids of differing lengths come back verbatim, never coerced."""
    state = {"omarsar0": "123", "typesafeai": "1942857309483188583"}
    path = _write(tmp_path / "watch_state.json", json.dumps(state))
    loaded = load_state(path)
    assert loaded == state
    assert all(isinstance(value, str) for value in loaded.values())


def test_long_snowflake_id_does_not_lose_precision(tmp_path: Path) -> None:
    """F9: a 19-digit snowflake id is not float-formatted (`1e+18`) or truncated."""
    long_id = "1942857309483188583"
    path = _write(tmp_path / "watch_state.json", json.dumps({"a": long_id}))
    assert load_state(path) == {"a": long_id}


def test_json_number_values_coerced_via_str(tmp_path: Path) -> None:
    """F16: JSON numbers are coerced losslessly via `str()`."""
    path = _write(tmp_path / "watch_state.json", '{"omarsar0": 1942857309483188583}')
    assert load_state(path) == {"omarsar0": "1942857309483188583"}


def test_corrupt_state_aborts_naming_path_and_json_error(tmp_path: Path) -> None:
    """F14: invalid JSON aborts; never silently resets to `{}`."""
    path = _write(tmp_path / "watch_state.json", '{"omarsar0": "123",')
    with pytest.raises(ValueError) as excinfo:
        load_state(path)
    assert str(path) in str(excinfo.value)


def test_truncated_state_file_aborts(tmp_path: Path) -> None:
    """F14: a truncated write from a killed prior run aborts, not resets."""
    path = _write(tmp_path / "watch_state.json", '{"omarsar0":')
    with pytest.raises(ValueError) as excinfo:
        load_state(path)
    assert str(path) in str(excinfo.value)


def test_empty_state_file_aborts_as_corrupt(tmp_path: Path) -> None:
    """F14: an empty file is invalid JSON and aborts like any corrupt file."""
    path = _write(tmp_path / "watch_state.json", "")
    with pytest.raises(ValueError) as excinfo:
        load_state(path)
    assert str(path) in str(excinfo.value)


@pytest.mark.parametrize("bad", ['["omarsar0"]', '"omarsar0"', "null", "42"])
def test_wrong_top_level_shape_aborts(tmp_path: Path, bad: str) -> None:
    """F15: list/string/null/number top level errors naming path and expected shape."""
    path = _write(tmp_path / "watch_state.json", bad)
    with pytest.raises(ValueError) as excinfo:
        load_state(path)
    message = str(excinfo.value)
    assert str(path) in message


@pytest.mark.parametrize("bad_value", ["null", "true", "[\"1\"]", '{"id": "1"}'])
def test_wrong_value_type_aborts_naming_handle(tmp_path: Path, bad_value: str) -> None:
    """F16: null/bool/list/dict values abort with an error naming the handle key."""
    path = _write(
        tmp_path / "watch_state.json",
        '{"goodhartproof": "99", "omarsar0": %s}' % bad_value,
    )
    with pytest.raises(ValueError) as excinfo:
        load_state(path)
    assert "omarsar0" in str(excinfo.value)
