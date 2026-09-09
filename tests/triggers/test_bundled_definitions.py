"""Tests for bundled trigger definitions (`docs/triggers/*.json`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fleet.triggers.model import Trigger, TriggerEvent
from fleet.triggers.render import render
from fleet.triggers.sources import SOURCES

_BUNDLED_DIR = Path(__file__).resolve().parents[2] / "docs" / "triggers"

#: Every key the `blocked_task` source emits (see sources/blocked_task.py).
_BLOCKED_TASK_PAYLOAD: dict[str, str] = {
    "task_id": "fleet-abc",
    "title": "stuck task",
    "blocked_reason": "failure streak",
    "blocked_at": "2026-09-09T00:00:00+00:00",
    "cwd": "/tmp/repo",
    "task_dir": "/tmp/tasks/fleet-abc",
    "coder": "claude",
    "model": "sonnet",
    "rounds": "3",
    "result_status": "blocked",
    "stderr_tail": "boom",
}

_CREATED_AT = "2026-09-09T00:00:00+00:00"


def _bundled_files() -> list[Path]:
    """Sorted bundled definition files, failing when none exist."""
    files = sorted(_BUNDLED_DIR.glob("*.json"))
    assert files, f"no bundled triggers in {_BUNDLED_DIR}"
    return files


def _load_trigger(path: Path) -> Trigger:
    """One bundled file plus timestamps, parsed via `Trigger.from_dict`."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("created_at", _CREATED_AT)
    data.setdefault("updated_at", _CREATED_AT)
    return Trigger.from_dict(data)


def _event() -> TriggerEvent:
    """One event carrying every `blocked_task` payload key."""
    return TriggerEvent(
        source="blocked_task",
        key="fleet-abc@2026-09-09T00:00:00+00:00",
        occurred_at=_CREATED_AT,
        payload=dict(_BLOCKED_TASK_PAYLOAD),
    )


def test_bundled_definitions_load() -> None:
    """Every bundled file parses after import fills id/timestamps."""
    for path in _bundled_files():
        assert _load_trigger(path).id
        assert _load_trigger(path).title


def test_bundled_source_known() -> None:
    """Every bundled definition names a registered source kind."""
    for path in _bundled_files():
        assert _load_trigger(path).source in SOURCES, path.name


def test_bundled_templates_render_clean() -> None:
    """Full payload leaves no `{{event.` placeholder in title/description."""
    for path in _bundled_files():
        trigger = _load_trigger(path)
        event = _event()
        assert "{{event." not in render(trigger.title, trigger=trigger, event=event, firing_n=1)
        rendered = render(trigger.description, trigger=trigger, event=event, firing_n=1)
        assert "{{event." not in rendered, path.name


def test_bundled_description_size() -> None:
    """Worker prompt stays small enough to fit the attempt budget."""
    for path in _bundled_files():
        assert len(_load_trigger(path).description.encode()) <= 3 * 1024, path.name


def test_investigator_runs_without_isolation() -> None:
    """The investigator analyses only, so it must not change code."""
    trigger = _load_trigger(_BUNDLED_DIR / "blocked-task-investigator.json")
    assert trigger.isolation == "none"
