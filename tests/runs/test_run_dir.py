"""Tests for fleet.runs.run_dir."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import pytest

from fleet.runs.run_dir import (
    NO_ITEM,
    create_run_dir,
    create_step_dir,
    flow_copy,
    inputs_file,
    new_run_id,
    outputs_file,
    read_outputs,
    run_dir,
    runs_root,
    step_dir,
)


def test_runs_root(tmp_path: Path) -> None:
    assert runs_root(tmp_path) == tmp_path / "runs"


def test_run_dir(tmp_path: Path) -> None:
    assert run_dir(tmp_path, "run-20260928-k3x9qa") == tmp_path / "runs" / "run-20260928-k3x9qa"


def test_flow_copy_and_inputs_file(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "run-1"
    assert flow_copy(root) == root / "flow.yaml"
    assert inputs_file(root) == root / "inputs.json"


def test_step_dir_plain(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "run-1"
    assert step_dir(root, "requirements") == root / "requirements"
    assert step_dir(root, "requirements", NO_ITEM) == root / "requirements"


def test_step_dir_item(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "run-1"
    assert step_dir(root, "failures", 0) == root / "failures" / "items" / "0"
    assert step_dir(root, "failures", 12) == root / "failures" / "items" / "12"


def test_outputs_file(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "run-1" / "requirements"
    assert outputs_file(root) == root / "outputs" / "outputs.json"


def test_read_outputs_missing_is_empty(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "run-1" / "requirements"
    target.mkdir(parents=True)
    assert read_outputs(target) == {}


def test_read_outputs_invalid_is_empty(tmp_path: Path, caplog) -> None:
    target = tmp_path / "runs" / "run-1" / "requirements"
    (target / "outputs").mkdir(parents=True)
    outputs_file(target).write_text("not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert read_outputs(target) == {}
    assert "outputs_invalid" in caplog.text


def test_read_outputs_non_object_is_empty(tmp_path: Path, caplog) -> None:
    target = tmp_path / "runs" / "run-1" / "requirements"
    (target / "outputs").mkdir(parents=True)
    outputs_file(target).write_text("[1, 2]", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert read_outputs(target) == {}
    assert "outputs_invalid" in caplog.text


def test_read_outputs_valid_preserves_types(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "run-1" / "requirements"
    (target / "outputs").mkdir(parents=True)
    payload = {"units": ["M1", "M2"], "count": 2, "ok": True, "name": "x"}
    outputs_file(target).write_text(json.dumps(payload), encoding="utf-8")
    found = read_outputs(target)
    assert found == payload
    assert isinstance(found["units"], list)
    assert isinstance(found["count"], int)
    assert isinstance(found["ok"], bool)


def test_new_run_id_format_and_unique() -> None:
    now = datetime(2026, 9, 28, 12, 0, 0)
    first = new_run_id(now)
    second = new_run_id(now)
    assert re.fullmatch(r"run-\d{8}-[a-z2-7]{6}", first)
    assert first.startswith("run-20260928-")
    assert first != second


def test_create_run_dir(tmp_path: Path) -> None:
    flow_source = tmp_path / "example.yaml"
    flow_source.write_bytes(b"fleet_flow: 2\n")
    target = create_run_dir(tmp_path, "run-1", flow_source, {"repo": "x", "n": 1})
    assert target == tmp_path / "runs" / "run-1"
    assert flow_copy(target).read_bytes() == b"fleet_flow: 2\n"
    assert json.loads(inputs_file(target).read_text(encoding="utf-8")) == {"repo": "x", "n": 1}
    with pytest.raises(FileExistsError):
        create_run_dir(tmp_path, "run-1", flow_source, {})


def test_create_step_dir_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "run-1"
    root.mkdir(parents=True)
    first = create_step_dir(root, "requirements")
    assert first == root / "requirements"
    assert (first / "outputs").is_dir()
    marker = first / "outputs" / "outputs.json"
    marker.write_text("{}", encoding="utf-8")
    second = create_step_dir(root, "requirements")
    assert second == first
    assert marker.read_text(encoding="utf-8") == "{}"
    item = create_step_dir(root, "failures", 3)
    assert item == root / "failures" / "items" / "3"
    assert (item / "outputs").is_dir()
