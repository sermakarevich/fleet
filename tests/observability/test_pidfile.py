"""Tests for observability/pidfile.py. Mirrors the source path."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.observability import pidfile as pidfile_mod
from fleet.observability.pidfile import PidFile


def _path(tmp_path: Path) -> Path:
    return tmp_path / ".svc.pid"


def test_v1_round_trip(tmp_path: Path) -> None:
    """write() then read() returns every field, tagged version 1."""
    path = _path(tmp_path)
    record = PidFile(
        pid=4242,
        started_at="2026-09-08T00:00:00+00:00",
        fingerprint="abc123",
        extra={"port": 7890, "host": "127.0.0.1"},
    )
    pidfile_mod.write(path, record)

    assert pidfile_mod.read(path) == record
    assert pidfile_mod.read(path) is not None
    assert pidfile_mod.read(path).version == 1  # type: ignore[union-attr]


def test_v1_marks_version_on_disk(tmp_path: Path) -> None:
    """The version marker is in the JSON so future readers can branch on it."""
    path = _path(tmp_path)
    pidfile_mod.write(path, PidFile(pid=7))
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_legacy_bare_int_reads_as_version_0(tmp_path: Path) -> None:
    """Pre-version `{pid}` text files (what the old route wrote) still read."""
    path = _path(tmp_path)
    path.write_text("12345", encoding="utf-8")
    assert pidfile_mod.read(path) == PidFile(version=0, pid=12345)


def test_legacy_json_int_reads_as_version_0(tmp_path: Path) -> None:
    """A JSON integer payload reads as a legacy record."""
    path = _path(tmp_path)
    path.write_text("12345", encoding="utf-8")
    record = pidfile_mod.read(path)
    assert record is not None
    assert (record.version, record.pid) == (0, 12345)


def test_legacy_dict_without_version_reads_as_version_0(tmp_path: Path) -> None:
    """Dicts written before the marker keep their fields and extras."""
    path = _path(tmp_path)
    path.write_text(
        json.dumps(
            {
                "pid": 4242,
                "started_at": "2026-09-08T00:00:00+00:00",
                "version_fingerprint": "abc123",
                "port": 7890,
            }
        ),
        encoding="utf-8",
    )
    record = pidfile_mod.read(path)
    assert record == PidFile(
        version=0,
        pid=4242,
        started_at="2026-09-08T00:00:00+00:00",
        fingerprint="abc123",
        extra={"port": 7890},
    )


def test_missing_file_reads_as_none(tmp_path: Path) -> None:
    assert pidfile_mod.read(_path(tmp_path)) is None


def test_garbage_reads_as_none(tmp_path: Path) -> None:
    """Non-numeric text and non-dict JSON never become a record."""
    path = _path(tmp_path)
    path.write_text("not-a-pid", encoding="utf-8")
    assert pidfile_mod.read(path) is None
    path.write_text(json.dumps(["pid", 1]), encoding="utf-8")
    assert pidfile_mod.read(path) is None
    path.write_text(json.dumps({"started_at": "x"}), encoding="utf-8")
    assert pidfile_mod.read(path) is None
