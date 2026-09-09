"""The compaction step: shrink STATE.md before a continue launch (ADR 0003).

Runs BEFORE the ``prepare_continue`` step inside ``ContinueLargeTask`` when
``core.launch.plan_launch(...).needs_compaction`` is true. Inputs are bounded
BY CONSTRUCTION — never raw logs: the current STATE.md, the last 3 attempt
summaries (derived via ``state/attempt_summary.py``, 4 KB each), the last
RESULT.json, and a short git log/status of the workdir. A cheap model call
rewrites STATE.md (``state_max_bytes`` cap); any failure falls back to the
pure ``core.compaction_fallback`` truncation so the launch still works.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fleet.coders import resolve_coder
from fleet.coders.base import Coder, Workspace
from fleet.core.compaction_fallback import compact_fallback
from fleet.core.errors import Json
from fleet.core.retry_policy import Action
from fleet.core.task import AttemptKind, EventKind, Task, TaskOutcome
from fleet.state import attempts as state_attempts
from fleet.state.artifacts import StateFile
from fleet.state.attempt_summary import render_markdown, summarize
from fleet.state.paths import RUN_JSON

from .base import FnStep, StepContext, StepResult, StepStatus, write_run_json
from .session.process import KILL_GRACE_SEC, CoderProcess
from .session.stream import EventStream

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

COMPACT_TIMEOUT_SEC = 180
STATE_INPUT_MAX_BYTES = 8192
SUMMARY_MAX_BYTES = 4096
SUMMARY_COUNT = 3
RESULT_MAX_BYTES = 4096
GIT_LOG_LINES = 30
GIT_STATUS_LINES = 30
TOTAL_INPUT_CAP_BYTES = 24 * 1024

_FENCED_STATE = re.compile(r"```STATE\s*\n(.*?)```", re.DOTALL)


@dataclass
class CompactionMaterial:
    """Bounded inputs for the compaction prompt. Never raw logs."""

    state: str = ""
    summaries: list[str] = field(default_factory=list)
    result_text: str = ""
    git_log: list[str] = field(default_factory=list)
    git_status: list[str] = field(default_factory=list)


def _read_capped(path: Path, max_bytes: int) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="ignore")
    return data[:max_bytes].decode("utf-8", errors="ignore")


def _git_lines(workdir: Path | None, args: list[str], limit: int) -> list[str]:
    if workdir is None or not workdir.is_dir():
        return []
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()][:limit]


def _workdir_of(ctx: StepContext) -> Path | None:
    """Workdir for git context: the isolated worktree, else the task cwd."""
    raw = Workspace(task_dir=ctx.task_dir, cwd=ctx.task.cwd).workdir
    return Path(raw) if raw else None


def collect_material(
    task_dir: Path,
    workdir: Path | None,
    before_n: int | None = None,
) -> CompactionMaterial:
    """Gather bounded compaction inputs; truncate oldest summaries first.

    *before_n* excludes the in-flight attempt's own (possibly empty) folder
    when looking for the last 3 attempts. Summaries are derived on demand
    (never stored) via ``state/attempt_summary.py``.
    """
    mat = CompactionMaterial(
        state=_read_capped(StateFile.path(task_dir), STATE_INPUT_MAX_BYTES),
        result_text=_read_capped(task_dir / "RESULT.json", RESULT_MAX_BYTES),
    )
    prev_ns: list[int] = []
    for row in state_attempts.load_attempts(task_dir):
        n = row.get("n")
        if not isinstance(n, int):
            continue
        if before_n is not None and n >= before_n:
            continue
        prev_ns.append(n)
    prev_ns = prev_ns[-SUMMARY_COUNT:] if len(prev_ns) > SUMMARY_COUNT else prev_ns
    for n in prev_ns:
        try:
            text = render_markdown(summarize(task_dir, n))
        except (OSError, ValueError):
            continue
        if text.strip():
            mat.summaries.append(text[:SUMMARY_MAX_BYTES])
    mat.git_log = _git_lines(workdir, ["log", "--oneline", "-30"], GIT_LOG_LINES)
    mat.git_status = _git_lines(workdir, ["status", "--short"], GIT_STATUS_LINES)

    total = sum(len(s.encode("utf-8")) for s in [mat.state, mat.result_text, *mat.summaries])
    while total > TOTAL_INPUT_CAP_BYTES and mat.summaries:
        dropped = mat.summaries.pop(0)
        total -= len(dropped.encode("utf-8"))
    return mat


def render_compaction_prompt(material: CompactionMaterial) -> str:
    """Template instruction + bounded material sections."""
    try:
        instruction = (_TEMPLATES_DIR / "COMPACTION.md").read_text(encoding="utf-8").strip()
    except OSError:
        instruction = (
            "Write a STATE.md (Done / In flight / Next / Facts) for the next "
            "worker. Output ONLY the file as one fenced block labelled STATE."
        )
    parts = [instruction, "## Current STATE.md\n" + (material.state or "(empty)")]
    for i, summary in enumerate(material.summaries, 1):
        parts.append(f"## Attempt summary {i}\n{summary}")
    if material.result_text.strip():
        parts.append("## Last RESULT.json\n" + material.result_text)
    if material.git_log:
        parts.append("## git log --oneline -30\n" + "\n".join(material.git_log))
    if material.git_status:
        parts.append("## git status --short\n" + "\n".join(material.git_status))
    return "\n\n".join(parts)


def _compaction_argv(coder: Coder, task: Task, task_dir: Path, prompt: str) -> list[str]:
    """Build the cheap-model argv through the coder's own argv shape.

    Reuses ``coder.build_argv`` (prompt is always the last element) and swaps
    in the compaction prompt; for claude adds a hard ``--max-turns 2`` cap.
    """
    argv = list(coder.build_argv(task, task_dir, None))
    if not argv:
        raise ValueError("coder.build_argv returned empty argv")
    argv[-1] = prompt
    coder_name = coder.spec.name
    if coder_name == "claude":
        argv.insert(-1, "--max-turns")
        argv.insert(-1, "2")
    return argv


def parse_compaction_output(text: str) -> str | None:
    """Extract the new STATE.md from the fenced STATE block."""
    match = _FENCED_STATE.search(text)
    if match is None:
        return None
    state = match.group(1).strip()
    return state or None


def _extract_text(raw: Json) -> str:
    """Best-effort plain text from one assistant event payload."""
    if not isinstance(raw, dict):
        return ""
    msg = raw.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, list):
            texts = [
                text
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
                for text in [b.get("text")]
                if isinstance(text, str) and text
            ]
            joined = "\n".join(texts)
            if joined:
                return joined
    for key in ("text", "message"):
        val = raw.get(key)
        if isinstance(val, str) and val:
            return val
    return json.dumps(raw)[:4000]


async def _run_compaction_model(
    coder: Coder,
    task: Task,
    argv: list[str],
    task_dir: Path,
    compact_dir: Path,
    timeout_sec: int = COMPACT_TIMEOUT_SEC,
) -> str:
    """Spawn the cheap model, stream its events into the compact attempt dir.

    Returns the concatenated assistant_text output. Raises ``TimeoutError``
    on timeout, ``OSError`` when the CLI binary is missing.
    """
    env = {**os.environ, **coder.env(task, task_dir)}
    proc = await CoderProcess.start(list(argv), env, None)
    stream = EventStream(
        proc,
        coder,
        attempt_dir=compact_dir,
        started_at=datetime.now(tz=UTC),
    )
    texts: list[str] = []
    try:
        async with asyncio.timeout(timeout_sec):
            async for evt in stream:
                if evt.kind == EventKind.ASSISTANT_TEXT:
                    text = _extract_text(evt.raw)
                    if text:
                        texts.append(text)
    except TimeoutError as exc:
        raise TimeoutError("compaction timed out") from exc
    finally:
        await proc.terminate_group(KILL_GRACE_SEC)
    return "\n".join(texts)


async def compact(ctx: StepContext) -> StepResult:
    """Rewrite STATE.md within its byte cap (the compact step's run function).

    Journals its own ``kind="compact"`` attempt row (visible and costed in
    the Attempts timeline) but never fails the worker: any model failure,
    timeout, or over-cap output falls back to the pure truncation in
    ``core.compaction_fallback`` and logs ``compaction_fallback``.
    """
    task_dir = ctx.task_dir
    state_cap = ctx.config.state_max_bytes
    if not ctx.config.compaction_enabled:
        return StepResult(status=StepStatus.OK, reason="compaction disabled")

    try:
        coder = resolve_coder(
            ctx.config.compaction_coder,
            model=ctx.config.compaction_model,
            fleet_home=ctx.fleet_home,
        )
    except ValueError as exc:
        ctx.log.warning("compaction_fallback", reason=f"unknown coder: {exc}")
        return _compact_fallback(ctx, f"unknown coder: {exc}")

    material = collect_material(task_dir, _workdir_of(ctx), before_n=ctx.attempt_n)
    prompt = render_compaction_prompt(material)
    try:
        argv = _compaction_argv(coder, ctx.task, task_dir, prompt)
    except (ValueError, TypeError, AttributeError) as exc:
        ctx.log.warning("compaction_fallback", reason=f"argv build failed: {exc}")
        return _compact_fallback(ctx, "argv build failed")

    compact_n = state_attempts.record_start(
        task_dir,
        coder=ctx.config.compaction_coder,
        model=ctx.config.compaction_model,
        worker="task.continue_large",
        kind=AttemptKind.COMPACT.value,
    )
    compact_dir = state_attempts.attempt_dir(task_dir, compact_n)
    compact_dir.mkdir(parents=True, exist_ok=True)
    write_run_json(
        compact_dir / RUN_JSON,
        launch={"mode": "compact", "pack_bytes": 0, "kind": AttemptKind.COMPACT.value},
    )
    fallback_reason: str | None = None
    try:
        output = await _run_compaction_model(coder, ctx.task, argv, task_dir, compact_dir)
    except (TimeoutError, OSError) as exc:
        fallback_reason = f"model call failed: {exc}"
        output = ""
    parsed = parse_compaction_output(output) if not fallback_reason else None
    if parsed is not None and len(parsed.encode("utf-8")) > state_cap:
        fallback_reason = "output violated byte cap"
        parsed = None
    if parsed is None:
        if fallback_reason is None:
            fallback_reason = "unparseable model output"
        ctx.log.warning("compaction_fallback", reason=fallback_reason)
        state = compact_fallback(
            material.state,
            material.summaries,
            material.result_text,
            material.git_log,
            task_id=ctx.task.id,
            max_bytes=state_cap,
        )
        outcome_reason = f"compaction_fallback: {fallback_reason}"
    else:
        state = parsed
        outcome_reason = "compacted"
    try:
        StateFile.write(task_dir, state)
    except OSError as exc:
        _finish_compact_row(ctx, compact_n, TaskOutcome.FAILURE, str(exc))
        return StepResult(status=StepStatus.FAIL, reason=f"compaction write failed: {exc}")
    _finish_compact_row(ctx, compact_n, TaskOutcome.SUCCESS, outcome_reason)
    return StepResult(status=StepStatus.OK, reason=outcome_reason)


def _compact_fallback(ctx: StepContext, reason: str) -> StepResult:
    """Truncate STATE.md deterministically when the model path is unavailable."""
    material = collect_material(ctx.task_dir, _workdir_of(ctx), before_n=ctx.attempt_n)
    state = compact_fallback(
        material.state,
        material.summaries,
        material.result_text,
        material.git_log,
        task_id=ctx.task.id,
        max_bytes=ctx.config.state_max_bytes,
    )
    try:
        StateFile.write(ctx.task_dir, state)
    except OSError as exc:
        return StepResult(status=StepStatus.FAIL, reason=f"compaction write failed: {exc}")
    ctx.log.warning("compaction_fallback", reason=reason)
    return StepResult(status=StepStatus.OK, reason=f"compaction_fallback: {reason}")


def _finish_compact_row(ctx: StepContext, n: int, outcome: TaskOutcome, reason: str) -> None:
    """Close the compact attempt row, warning (never raising) on failure."""
    try:
        state_attempts.record_end(
            ctx.task_dir,
            outcome=outcome,
            exit_code=0,
            reason=reason,
            action=Action.CLOSE,
            n=n,
        )
    except OSError as exc:
        ctx.log.warning("attempt_record_failed", error=str(exc))


COMPACT_STEP = FnStep("compact", compact)
