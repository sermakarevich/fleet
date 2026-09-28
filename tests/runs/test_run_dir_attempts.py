"""Tests for attempt/check paths and verdict reading in fleet.runs.run_dir."""

from __future__ import annotations

import json
from pathlib import Path

from fleet.runs.run_dir import (
    attempt_dir,
    attempts_root,
    check_file,
    checks_dir,
    latest_attempt_dir,
    read_verdicts,
)


def test_attempt_and_check_paths(tmp_path: Path) -> None:
    step = tmp_path / "run-1" / "draft"
    assert attempts_root(step) == step / "attempts"
    assert attempt_dir(step, 0) == step / "attempts" / "0"
    assert attempt_dir(step, 3) == step / "attempts" / "3"
    assert checks_dir(step / "attempts" / "2") == step / "attempts" / "2" / "checks"
    assert (
        check_file(step / "attempts" / "2", "voice")
        == step / "attempts" / "2" / "checks" / "voice.json"
    )


def test_latest_attempt_dir_none_when_missing(tmp_path: Path) -> None:
    step = tmp_path / "run-1" / "draft"
    step.mkdir(parents=True)
    assert latest_attempt_dir(step) is None


def test_latest_attempt_dir_none_when_no_numbered_folders(tmp_path: Path) -> None:
    step = tmp_path / "run-1" / "draft"
    (attempts_root(step) / "scratch").mkdir(parents=True)
    assert latest_attempt_dir(step) is None


def test_latest_attempt_dir_single(tmp_path: Path) -> None:
    step = tmp_path / "run-1" / "draft"
    attempt_dir(step, 1).mkdir(parents=True)
    assert latest_attempt_dir(step) == attempt_dir(step, 1)


def test_latest_attempt_dir_highest_and_ignores_non_numeric(tmp_path: Path) -> None:
    step = tmp_path / "run-1" / "draft"
    for name in ("0", "2", "10", "latest", "tmp"):
        (attempts_root(step) / name).mkdir(parents=True)
    assert latest_attempt_dir(step) == attempt_dir(step, 10)


def _write_verdict(attempt: Path, name: str, payload: object) -> None:
    folder = checks_dir(attempt)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_read_verdicts_empty_without_attempts(tmp_path: Path) -> None:
    step = tmp_path / "run-1" / "draft"
    step.mkdir(parents=True)
    assert read_verdicts(step) == {}


def test_read_verdicts_latest_attempt_only(tmp_path: Path) -> None:
    step = tmp_path / "run-1" / "draft"
    _write_verdict(attempt_dir(step, 0), "voice", {"name": "voice", "ok": True, "message": "ok"})
    _write_verdict(
        attempt_dir(step, 1),
        "voice",
        {
            "name": "voice",
            "ok": False,
            "message": "off tone",
            "outputs": {"problems": ["flat"]},
            "duration_s": 1.5,
        },
    )
    found = read_verdicts(step)
    assert found == {
        "voice": {
            "name": "voice",
            "ok": False,
            "message": "off tone",
            "outputs": {"problems": ["flat"]},
            "duration_s": 1.5,
        }
    }


def test_read_verdicts_skips_bad_files(tmp_path: Path) -> None:
    step = tmp_path / "run-1" / "draft"
    attempt = attempt_dir(step, 0)
    _write_verdict(attempt, "good", {"name": "good", "ok": True, "message": "fine"})
    _write_verdict(attempt, "broken", "not json{")
    _write_verdict(attempt, "listed", [1, 2, 3])
    found = read_verdicts(step)
    assert found == {"good": {"name": "good", "ok": True, "message": "fine"}}
