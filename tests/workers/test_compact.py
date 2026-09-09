"""Tests for workers/compact.py: the pre-continue compaction step."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import structlog

import fleet.workers.compact as compact_mod
from fleet.coders.base import CoderSpec
from fleet.core.config import RuntimeConfig
from fleet.core.retry_policy import _trailing_streak
from fleet.core.task import Event, EventKind, Task
from fleet.state import attempts as state_attempts
from fleet.state.paths import task_dir as _task_dir_path
from fleet.workers.base import FnStep, StepContext, StepStatus
from fleet.workers.compact import (
    COMPACT_STEP,
    collect_material,
    parse_compaction_output,
    render_compaction_prompt,
)
from fleet.workers.llm_session import LlmSession
from fleet.workers.task import ContinueLargeTask, ContinueTask, plan_task

_STATE_BODY = (
    "## Plan\n- plan\n\n## Done\n- shipped x\n\n## In flight\n- y\n\n"
    "## Next\n- z\n\n## Facts\n- fleet uses beads\n"
)

_SUCCESS_LINES = [
    json.dumps({"text": "```STATE\n" + _STATE_BODY + "\n```"}),
]

_OVERSIZE_LINES = [
    json.dumps({"text": "```STATE\n" + "x" * 20000 + "\n```"}),
]


def _emit_script(lines: list[str]) -> str:
    return (
        "import sys\n"
        f"lines = {lines!r}\n"
        "for line in lines:\n"
        "    sys.stdout.write(line + '\\n')\n"
        "    sys.stdout.flush()\n"
    )


class FakeCompactionCoder:
    """Coder double whose subprocess prints fixed JSON lines."""

    name = "fake"
    context_limit = 200_000
    spec = CoderSpec(name="fake", default_model="fake", context_limit=200_000)

    lines: list[str] = _SUCCESS_LINES

    def __init__(self, model: str = "fake", fleet_home: Path | None = None) -> None:
        self.model = model
        self.fleet_home = fleet_home

    def build_argv(self, task: Task, task_dir: Path, plan=None) -> list[str]:
        return [sys.executable, "-c", _emit_script(list(self.lines)), "__PROMPT__"]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        return {
            "FLEET_TASK_ID": task.id,
            "FLEET_TASK_DIR": str(task_dir),
        }

    def normalize_event(self, raw_line: str) -> Event | None:
        try:
            data = json.loads(raw_line)
        except ValueError:
            return None
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return Event(kind=EventKind.ASSISTANT_TEXT, raw=data, ts=datetime.now())
        return None


class _Gauge:
    def update(self, evt: Event) -> None:
        return None


def _setup_task_dir(tmp_path: Path, task_id: str = "t-compact") -> tuple[Task, Path]:
    task = Task(id=task_id, title="T", description=None, status="in_progress")
    task_dir = _task_dir_path(tmp_path, task_id)
    task_dir.mkdir(parents=True)
    (task_dir / "STATE.md").write_text(f"# {task_id} — STATE\n\n" + _STATE_BODY)
    return task, task_dir


def _ctx(
    task: Task, task_dir: Path, attempt_n: int, config: RuntimeConfig | None = None
) -> StepContext:
    return StepContext(
        task=task,
        task_dir=task_dir,
        workdir=task_dir,
        fleet_home=task_dir,
        coder=None,
        config=config or RuntimeConfig(),
        rate_gauge=_Gauge(),  # type: ignore[arg-type]
        log=structlog.get_logger(),
        attempt_dir=state_attempts.attempt_dir(task_dir, attempt_n),
        attempt_n=attempt_n,
    )


def _patch_coder(monkeypatch, lines: list[str]) -> None:
    FakeCompactionCoder.lines = lines

    def _resolve_coder(name: str, **kwargs):
        return FakeCompactionCoder(**kwargs)

    monkeypatch.setattr("fleet.workers.compact.resolve_coder", _resolve_coder)


# ---------------------------------------------------------------------------
# parse_compaction_output
# ---------------------------------------------------------------------------


def test_parse_single_state_block() -> None:
    assert parse_compaction_output("```STATE\nstate-body\n```") == "state-body"


def test_parse_missing_block_returns_none() -> None:
    assert parse_compaction_output("```HANDOFF\nold style\n```") is None
    assert parse_compaction_output("no fences at all") is None


# ---------------------------------------------------------------------------
# Happy path: fake coder emitting one STATE block
# ---------------------------------------------------------------------------


def test_compact_writes_state_and_compact_row(tmp_path: Path, monkeypatch) -> None:
    _patch_coder(monkeypatch, _SUCCESS_LINES)
    task, task_dir = _setup_task_dir(tmp_path)
    outer_n = state_attempts.record_start(task_dir, coder="claude", model="sonnet")
    ctx = _ctx(task, task_dir, outer_n)

    result = asyncio.run(COMPACT_STEP.run(ctx))

    assert result.status == StepStatus.OK
    assert result.reason == "compacted"
    assert (task_dir / "STATE.md").read_text() == _STATE_BODY.strip()

    rows = state_attempts.load_attempts(task_dir)
    compact_rows = [r for r in rows if r.get("kind") == "compact"]
    assert len(compact_rows) == 1
    assert compact_rows[0]["outcome"] == "success"
    compact_dir = state_attempts.attempt_dir(task_dir, compact_rows[0]["n"])
    run = json.loads((compact_dir / "run.json").read_text(encoding="utf-8"))
    assert run["launch"] == {"mode": "compact", "pack_bytes": 0, "kind": "compact"}
    assert not (compact_dir / "launch.json").exists()
    assert (compact_dir / "events.jsonl").exists()


# ---------------------------------------------------------------------------
# Oversize output → deterministic fallback
# ---------------------------------------------------------------------------


def test_oversize_output_falls_back(tmp_path: Path, monkeypatch) -> None:
    _patch_coder(monkeypatch, _OVERSIZE_LINES)
    task, task_dir = _setup_task_dir(tmp_path)
    outer_n = state_attempts.record_start(task_dir, coder="claude", model="sonnet")
    ctx = _ctx(task, task_dir, outer_n)

    result = asyncio.run(COMPACT_STEP.run(ctx))

    assert result.status == StepStatus.OK
    assert result.reason.startswith("compaction_fallback")
    state = (task_dir / "STATE.md").read_text()
    assert len(state.encode("utf-8")) <= ctx.config.state_max_bytes
    assert "## Next" in state


# ---------------------------------------------------------------------------
# Timeout → fallback
# ---------------------------------------------------------------------------


def test_timeout_falls_back(tmp_path: Path, monkeypatch) -> None:
    _patch_coder(monkeypatch, _SUCCESS_LINES)
    task, task_dir = _setup_task_dir(tmp_path)
    outer_n = state_attempts.record_start(task_dir, coder="claude", model="sonnet")
    ctx = _ctx(task, task_dir, outer_n)

    async def _boom(*args, **kwargs) -> str:
        raise TimeoutError("compaction timed out")

    monkeypatch.setattr(compact_mod, "_run_compaction_model", _boom)

    result = asyncio.run(COMPACT_STEP.run(ctx))

    assert result.status == StepStatus.OK
    assert result.reason.startswith("compaction_fallback")
    assert (task_dir / "STATE.md").exists()


# ---------------------------------------------------------------------------
# Inputs never include events/log files
# ---------------------------------------------------------------------------


def test_inputs_exclude_events_and_logs(tmp_path: Path) -> None:
    """Raw events/log lines are never pasted wholesale; only the derived,
    bounded summary (tool counts, capped tails) feeds the prompt."""
    task, task_dir = _setup_task_dir(tmp_path)
    n = state_attempts.record_start(task_dir, coder="claude", model="sonnet")
    adir = state_attempts.attempt_dir(task_dir, n)
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "events.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "kind": "tool_use",
                    "tool_name": "Read",
                    "raw": {"blob": "SUPERSECRET-EVENTS-MARKER-" + "x" * 500},
                }
            )
            for _ in range(50)
        )
        + "\n"
    )
    (adir / "run.json").write_text(
        json.dumps({"launch": {"mode": "fresh", "pack_bytes": 0, "kind": "work"}})
    )

    material = collect_material(task_dir, None, before_n=n + 1)
    prompt = render_compaction_prompt(material)

    assert "SUPERSECRET-EVENTS-MARKER" not in prompt
    assert "shipped x" in prompt  # real state material is present
    assert len(prompt.encode("utf-8")) <= compact_mod.TOTAL_INPUT_CAP_BYTES


def test_summaries_are_derived_not_stored(tmp_path: Path) -> None:
    """collect_material computes summaries; stale stored files are ignored."""
    task, task_dir = _setup_task_dir(tmp_path)
    n = state_attempts.record_start(task_dir, coder="claude", model="sonnet")
    adir = state_attempts.attempt_dir(task_dir, n)
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "run.json").write_text(
        json.dumps({"launch": {"mode": "continue", "pack_bytes": 5, "kind": "work"}})
    )

    material = collect_material(task_dir, None, before_n=n + 1)

    assert len(material.summaries) == 1
    assert "launch mode: continue" in material.summaries[0]


# ---------------------------------------------------------------------------
# plan_task wiring: needs_compaction → ContinueLargeTask
# ---------------------------------------------------------------------------


def test_plan_task_returns_continue_large_when_needs_compaction(tmp_path: Path) -> None:
    task, task_dir = _setup_task_dir(tmp_path)
    # Oversized STATE.md trips LaunchPlan.needs_compaction.
    (task_dir / "STATE.md").write_text("s" * 20000)
    state_attempts.record_start(task_dir, coder="claude", model="sonnet")
    ctx = _ctx(task, task_dir, 2)

    worker = plan_task(ctx)

    assert worker.name == ContinueLargeTask.name == "task.continue_large"
    assert [type(s) for s in worker.steps] == [FnStep, FnStep, LlmSession]


def test_plan_task_skips_compaction_when_disabled(tmp_path: Path) -> None:
    task, task_dir = _setup_task_dir(tmp_path)
    (task_dir / "STATE.md").write_text("s" * 20000)
    state_attempts.record_start(task_dir, coder="claude", model="sonnet")
    cfg = RuntimeConfig(compaction_enabled=False)
    ctx = _ctx(task, task_dir, 2, config=cfg)

    worker = plan_task(ctx)

    assert worker.name == ContinueTask.name


# ---------------------------------------------------------------------------
# Retry streaks skip kind=compact rows
# ---------------------------------------------------------------------------


def test_trailing_streak_skips_compact_rows(tmp_path: Path) -> None:
    task, task_dir = _setup_task_dir(tmp_path)
    n1 = state_attempts.record_start(task_dir, coder="c", model="m")
    state_attempts.record_end(
        task_dir, outcome="context_pressure", exit_code=None, reason="full", action="release", n=n1
    )
    n2 = state_attempts.record_start(task_dir, coder="c", model="m", kind="compact")
    state_attempts.record_end(
        task_dir, outcome="success", exit_code=0, reason="compacted", action="close", n=n2
    )

    history = state_attempts.load_attempts(task_dir)

    assert _trailing_streak(history, "context") == 1
