"""The compaction step: shrink artifacts before a continue launch (ADR 0003).

Runs BEFORE ``PrepareContinue`` inside ``ContinueLargeTask`` when
``core.launch.plan_launch(...).needs_compaction`` is true. Inputs are bounded
BY CONSTRUCTION — never raw logs: the current HANDOFF.md / KNOWLEDGE.md /
PLAN.md, the last 3 attempt SUMMARY.md files (4 KB each), the last
RESULT.json, and a short git log/status of the workdir. A cheap model call
rewrites HANDOFF.md (2 KB) + KNOWLEDGE.md (4 KB); any failure falls back to
the pure ``core.compaction_fallback`` truncation so the launch still works.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from fleet.core.compaction_fallback import compact_fallback
from fleet.state import attempts as state_attempts
from fleet.state.journal import append_event

from .base import StepContext, StepResult

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

COMPACT_TIMEOUT_SEC = 180
SUMMARY_MAX_BYTES = 4096
SUMMARY_COUNT = 3
GIT_LOG_LINES = 30
GIT_STATUS_LINES = 30
TOTAL_INPUT_CAP_BYTES = 24 * 1024

_FENCED = re.compile(r"```(HANDOFF|KNOWLEDGE)\s*\n(.*?)```", re.DOTALL)


@dataclass
class CompactionMaterial:
    """Bounded inputs for the compaction prompt. Never raw logs."""

    handoff: str = ""
    knowledge: str = ""
    plan: str = ""
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


def _resolve_workdir(ctx: StepContext) -> Path | None:
    wt_marker = ctx.task_dir / ".worktree"
    if wt_marker.exists():
        try:
            return Path(wt_marker.read_text(encoding="utf-8").strip())
        except OSError:
            return None
    if ctx.task.cwd:
        return Path(ctx.task.cwd)
    return None


def collect_material(
    task_dir: Path,
    workdir: Path | None,
    before_n: int | None = None,
) -> CompactionMaterial:
    """Gather bounded compaction inputs; truncate oldest summaries first.

    *before_n* excludes the in-flight attempt's own (possibly empty) folder
    when looking for the last 3 SUMMARY.md files and the last RESULT.json.
    """
    artifacts = task_dir / "artifacts"
    mat = CompactionMaterial(
        handoff=_read_capped(artifacts / "HANDOFF.md", 8192),
        knowledge=_read_capped(artifacts / "KNOWLEDGE.md", 8192),
        plan=_read_capped(artifacts / "PLAN.md", 8192),
        result_text=_read_capped(artifacts / "RESULT.json", 4096),
    )
    prev_dirs: list[Path] = []
    for row in state_attempts.load_attempts(task_dir):
        n = row.get("n")
        if not isinstance(n, int):
            continue
        if before_n is not None and n >= before_n:
            continue
        prev_dirs.append(state_attempts.attempt_dir(task_dir, n))
    prev_dirs = prev_dirs[-SUMMARY_COUNT:] if len(prev_dirs) > SUMMARY_COUNT else prev_dirs
    for d in prev_dirs:
        text = _read_capped(d / "SUMMARY.md", SUMMARY_MAX_BYTES)
        if text.strip():
            mat.summaries.append(text)
    mat.git_log = _git_lines(workdir, ["log", "--oneline", "-30"], GIT_LOG_LINES)
    mat.git_status = _git_lines(workdir, ["status", "--short"], GIT_STATUS_LINES)

    total = sum(
        len(s.encode("utf-8"))
        for s in [mat.handoff, mat.knowledge, mat.plan, mat.result_text, *mat.summaries]
    )
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
            "Write a HANDOFF.md <= 2000 bytes and a KNOWLEDGE.md <= 4000 bytes "
            "for the next worker. Output ONLY the two files as fenced blocks "
            "labelled HANDOFF and KNOWLEDGE."
        )
    parts = [instruction, "## Current HANDOFF.md\n" + (material.handoff or "(empty)")]
    parts.append("## Current KNOWLEDGE.md\n" + (material.knowledge or "(empty)"))
    if material.plan.strip():
        parts.append("## Current PLAN.md\n" + material.plan)
    for i, summary in enumerate(material.summaries, 1):
        parts.append(f"## Attempt summary {i}\n{summary}")
    if material.result_text.strip():
        parts.append("## Last RESULT.json\n" + material.result_text)
    if material.git_log:
        parts.append("## git log --oneline -30\n" + "\n".join(material.git_log))
    if material.git_status:
        parts.append("## git status --short\n" + "\n".join(material.git_status))
    return "\n\n".join(parts)


def _compaction_argv(coder: object, task: object, task_dir: Path, prompt: str) -> list[str]:
    """Build the cheap-model argv through the coder's own argv shape.

    Reuses ``coder.build_argv`` (prompt is always the last element) and swaps
    in the compaction prompt; for claude adds a hard ``--max-turns 2`` cap.
    """
    build = coder.build_argv
    argv = list(build(task, task_dir, None))
    if not argv:
        raise ValueError("coder.build_argv returned empty argv")
    argv[-1] = prompt
    if getattr(coder, "name", "") == "claude":
        argv.insert(-1, "--max-turns")
        argv.insert(-1, "2")
    return argv


def parse_compaction_output(text: str) -> tuple[str, str] | None:
    """Extract ``(handoff, knowledge)`` from fenced HANDOFF/KNOWLEDGE blocks."""
    found = dict(_FENCED.findall(text))
    handoff = found.get("HANDOFF", "").strip()
    knowledge = found.get("KNOWLEDGE", "").strip()
    if not handoff or not knowledge:
        return None
    return handoff, knowledge


def _extract_text(raw: object) -> str:
    if not isinstance(raw, dict):
        return ""
    msg = raw.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, list):
            texts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "\n".join(t for t in texts if t)
            if joined:
                return joined
    for key in ("text", "message"):
        val = raw.get(key)
        if isinstance(val, str) and val:
            return val
    return json.dumps(raw)[:4000]


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


async def _run_compaction_model(
    coder: object,
    task: object,
    argv: list[str],
    task_dir: Path,
    compact_dir: Path,
    timeout_sec: int = COMPACT_TIMEOUT_SEC,
) -> str:
    """Spawn the cheap model, stream its events into the compact attempt dir.

    Returns the concatenated assistant_text output. Raises ``TimeoutError``
    on timeout, ``OSError`` when the CLI binary is missing.
    """
    env = {**os.environ, **coder.env(task, task_dir)}  # type: ignore[attr-defined]
    proc = await asyncio.create_subprocess_exec(
        *argv,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    assert proc.stdout is not None
    proc.stdout._limit = 100 * 1024 * 1024
    texts: list[str] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_sec
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("compaction timed out")
            try:
                raw_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except TimeoutError:
                raise TimeoutError("compaction timed out") from None
            if not raw_bytes:
                break
            raw_line = raw_bytes.decode("utf-8", errors="replace").rstrip("\n")
            evt = coder.normalize_event(raw_line)  # type: ignore[attr-defined]
            if evt is None:
                continue
            try:
                append_event(compact_dir, evt)
            except OSError:
                pass
            if evt.kind == "assistant_text":
                text = _extract_text(evt.raw)
                if text:
                    texts.append(text)
    finally:
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
        else:
            await proc.wait()
    return "\n".join(texts)


class Compact:
    """Compaction step: rewrite HANDOFF.md/KNOWLEDGE.md within byte caps.

    Journals its own ``kind="compact"`` attempt row (visible and costed in
    the Attempts timeline) but never fails the worker: any model failure,
    timeout, or over-cap output falls back to the pure truncation in
    ``core.compaction_fallback`` and logs ``compaction_fallback``.
    """

    name = "compact"

    async def run(self, ctx: StepContext) -> StepResult:
        from fleet.coders import get_coder

        artifacts_dir = ctx.task_dir / "artifacts"
        handoff_cap = ctx.config.handoff_max_bytes
        knowledge_cap = ctx.config.knowledge_max_bytes
        if not ctx.config.compaction_enabled:
            return StepResult(status="ok", reason="compaction disabled")

        try:
            coder_cls = get_coder(ctx.config.compaction_coder)
        except ValueError as exc:
            ctx.log.warning("compaction_fallback", reason=f"unknown coder: {exc}")
            return self._fallback(ctx, artifacts_dir, handoff_cap, knowledge_cap, "unknown coder")

        coder = coder_cls(model=ctx.config.compaction_model)
        material = collect_material(ctx.task_dir, _resolve_workdir(ctx), before_n=ctx.attempt_n)
        prompt = render_compaction_prompt(material)
        try:
            argv = _compaction_argv(coder, ctx.task, ctx.task_dir, prompt)
        except (ValueError, TypeError, AttributeError) as exc:
            ctx.log.warning("compaction_fallback", reason=f"argv build failed: {exc}")
            return self._fallback(ctx, artifacts_dir, handoff_cap, knowledge_cap, "argv build failed")

        compact_n = state_attempts.record_start(
            ctx.task_dir,
            coder=ctx.config.compaction_coder,
            model=ctx.config.compaction_model,
            worker="task.continue_large",
            kind="compact",
        )
        compact_dir = state_attempts.attempt_dir(ctx.task_dir, compact_n)
        compact_dir.mkdir(parents=True, exist_ok=True)
        (compact_dir / "launch.json").write_text(
            json.dumps({"mode": "compact", "pack_bytes": len(prompt.encode()), "kind": "compact"}),
            encoding="utf-8",
        )
        fallback_reason: str | None = None
        try:
            output = await _run_compaction_model(coder, ctx.task, argv, ctx.task_dir, compact_dir)
        except (TimeoutError, OSError) as exc:
            fallback_reason = f"model call failed: {exc}"
            output = ""
        parsed = parse_compaction_output(output) if not fallback_reason else None
        if parsed is not None:
            handoff, knowledge = parsed
            if len(handoff.encode()) > handoff_cap or len(knowledge.encode()) > knowledge_cap:
                fallback_reason = "output violated byte caps"
                parsed = None
        if parsed is None:
            if fallback_reason is None:
                fallback_reason = "unparseable model output"
            ctx.log.warning("compaction_fallback", reason=fallback_reason)
            handoff, knowledge = compact_fallback(
                material.handoff,
                material.knowledge,
                material.summaries,
                material.git_log,
                handoff_cap,
                knowledge_cap,
            )
            outcome_reason = f"compaction_fallback: {fallback_reason}"
        else:
            outcome_reason = "compacted"
        try:
            _write_atomic(artifacts_dir / "HANDOFF.md", handoff)
            _write_atomic(artifacts_dir / "KNOWLEDGE.md", knowledge)
        except OSError as exc:
            self._finish_compact_row(ctx, compact_dir, compact_n, "failure", str(exc))
            return StepResult(status="fail", reason=f"compaction write failed: {exc}")
        self._finish_compact_row(ctx, compact_dir, compact_n, "success", outcome_reason)
        return StepResult(status="ok", reason=outcome_reason)

    def _fallback(
        self, ctx: StepContext, artifacts_dir: Path, handoff_cap: int, knowledge_cap: int, reason: str
    ) -> StepResult:
        material = collect_material(ctx.task_dir, _resolve_workdir(ctx), before_n=ctx.attempt_n)
        handoff, knowledge = compact_fallback(
            material.handoff, material.knowledge, material.summaries, material.git_log,
            handoff_cap, knowledge_cap,
        )
        try:
            _write_atomic(artifacts_dir / "HANDOFF.md", handoff)
            _write_atomic(artifacts_dir / "KNOWLEDGE.md", knowledge)
        except OSError as exc:
            return StepResult(status="fail", reason=f"compaction write failed: {exc}")
        ctx.log.warning("compaction_fallback", reason=reason)
        return StepResult(status="ok", reason=f"compaction_fallback: {reason}")

    def _finish_compact_row(
        self, ctx: StepContext, compact_dir: Path, n: int, outcome: str, reason: str
    ) -> None:
        try:
            state_attempts.record_end(
                ctx.task_dir, outcome=outcome, exit_code=0, reason=reason, action="close", n=n
            )
        except OSError as exc:
            ctx.log.warning("attempt_record_failed", error=str(exc))
            return
        summary = (
            f"# Attempt {n} summary (compaction)\n\n"
            f"- kind: compact\n- outcome: {outcome} ({reason})\n"
        )
        try:
            (compact_dir / "SUMMARY.md").write_text(summary[:4096], encoding="utf-8")
        except OSError as exc:
            ctx.log.warning("attempt_summary_failed", error=str(exc))

    async def cancel(self, reason: str) -> None:
        return None
