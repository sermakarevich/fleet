"""Typed-domain enums: every emitted kind is a member (ADR 0006 bead 18)."""

from __future__ import annotations

import ast
from pathlib import Path

from fleet.core.result import ResultStatus, parse_result
from fleet.core.retry_policy import Action
from fleet.core.task import AttemptKind, EventKind, TaskStatus
from fleet.orchestrator.triage import TriageApplyOutcome
from fleet.workers.base import StepStatus

SRC = Path(__file__).resolve().parents[2] / "src" / "fleet"

_KIND_MEMBERS = {m.value for m in EventKind} | {m.value for m in AttemptKind}


def _kind_literals() -> list[str]:
    """Every ``kind="<literal>"`` value constructed anywhere in src/fleet."""
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword):
                continue
            if node.arg != "kind":
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                found.append(f"{path}:{node.lineno}:{node.value.value}")
    return found


def test_every_kind_literal_is_a_member() -> None:
    """Every ``kind="..."`` in src/fleet names an EventKind or AttemptKind."""
    bad = [loc for loc in _kind_literals() if loc.rsplit(":", 1)[1] not in _KIND_MEMBERS]
    assert not bad, f"bare kind strings outside the enums: {bad}"


def test_event_kind_values() -> None:
    """The emitted event kinds, and only they, are members."""
    assert {m.value for m in EventKind} == {
        "assistant_text",
        "tool_use",
        "tool_result",
        "thinking",
        "rate_limit",
        "rate_limit_info",
        "session_started",
        "session_ended",
        "error",
    }


def test_task_status_values() -> None:
    """Bead statuses match the queue's vocabulary."""
    assert {m.value for m in TaskStatus} >= {"open", "in_progress", "blocked", "closed"}


def test_result_status_round_trip() -> None:
    """RESULT.json statuses parse to members; unknown statuses are None."""
    assert parse_result('{"status": "done"}') is not None
    assert parse_result('{"status": "done"}').status == ResultStatus.DONE  # type: ignore[union-attr]
    assert parse_result('{"status": "partial"}').status == ResultStatus.PARTIAL  # type: ignore[union-attr]
    assert parse_result('{"status": "blocked"}').status == ResultStatus.BLOCKED  # type: ignore[union-attr]
    assert parse_result('{"status": "finished"}') is None
    assert {m.value for m in ResultStatus} == {"done", "partial", "blocked"}


def test_step_status_values() -> None:
    """Step verdicts are ok, fail, or outcome."""
    assert {m.value for m in StepStatus} == {"ok", "fail", "outcome"}


def test_triage_apply_outcome_values() -> None:
    """Triage apply outcomes cover every return path."""
    assert {m.value for m in TriageApplyOutcome} == {
        "skipped",
        "closed",
        "ignored",
        "released-opus",
        "released",
        "ignored-all",
    }


def test_enums_compare_equal_to_plain_strings() -> None:
    """StrEnum members equal their JSON-edge strings (file formats unchanged)."""
    assert EventKind.ERROR == "error"
    assert TaskStatus.BLOCKED == "blocked"
    assert ResultStatus.DONE == "done"
    assert StepStatus.OK == "ok"
    assert AttemptKind.COMPACT == "compact"
    assert TriageApplyOutcome.SKIPPED == "skipped"
    assert Action.CLOSE.value == "close"
