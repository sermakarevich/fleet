from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import Protocol

import structlog

from fleet.coders.base import Coder
from fleet.logging import append_event, open_task_log
from fleet.queue import Queue
from fleet.schemas import Event, RuntimeConfig, Task, TaskOutcome, TaskOutcomeRecord, SHUTDOWN_GRACE_SEC

_STDERR_TAIL_BYTES = 2048

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _input_tokens(usage: dict) -> int:
    """Sum prompt-side tokens for context tracking; missing or non-int fields → 0."""
    def _int(v: object) -> int:
        return v if isinstance(v, int) and not isinstance(v, bool) else 0
    return (
        _int(usage.get("input_tokens"))
        + _int(usage.get("cache_creation_input_tokens"))
        + _int(usage.get("cache_read_input_tokens"))
    )


def _ensure_artifact_stubs(artifacts_dir: Path, task_id: str) -> None:
    """Create PLAN_AND_STATUS.md and KNOWLEDGE.md stubs if missing.

    Never overwrites existing content — agents own these files after the
    first run.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    plan_and_status = artifacts_dir / "PLAN_AND_STATUS.md"
    if not plan_and_status.exists():
        tmpl = (_TEMPLATES_DIR / "PLAN_AND_STATUS.md.tmpl").read_text(encoding="utf-8")
        plan_and_status.write_text(tmpl.format(task_id=task_id))
    knowledge = artifacts_dir / "KNOWLEDGE.md"
    if not knowledge.exists():
        tmpl = (_TEMPLATES_DIR / "KNOWLEDGE.md.tmpl").read_text(encoding="utf-8")
        knowledge.write_text(tmpl.format(task_id=task_id))


class RateGauge(Protocol):
    def update(self, evt: Event) -> None: ...


class TaskRunner:
    def __init__(
        self,
        task: Task,
        coder: Coder,
        queue: Queue,
        config: RuntimeConfig,
        rate_gauge: RateGauge,
        project_root: Path,
        fleet_home: Path,
        log: structlog.BoundLogger,
    ) -> None:
        self._task = task
        self._coder = coder
        self._queue = queue
        self._config = config
        self._rate_gauge = rate_gauge
        self._project_root = project_root
        self._fleet_home = fleet_home
        self._log = log
        self._proc: asyncio.subprocess.Process | None = None
        self._cancelled = False
        self._killed = False

    async def run(self) -> TaskOutcomeRecord:
        task = self._task

        task_dir = self._fleet_home / "tasks" / task.id
        artifacts_dir = task_dir / "artifacts"
        task_dir.mkdir(parents=True, exist_ok=True)
        _ensure_artifact_stubs(artifacts_dir, task.id)
        self._coder.write_runtime_config(self._project_root, task)

        with open_task_log(task_dir, task.id) as task_log:
            stderr_path = Path(task_log.stderr_file.name)

            argv = self._coder.build_argv(task, task_dir)
            extra_env = self._coder.env(task, task_dir)
            proc_env = {**os.environ, **extra_env}

            task_log.log.info(
                "subprocess_started",
                task_id=task.id,
                argv=argv,
            )

            proc = await asyncio.create_subprocess_exec(
                *argv,
                env=proc_env,
                cwd=self._project_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=task_log.stderr_file,
                stdin=asyncio.subprocess.DEVNULL,
            )
            self._proc = proc

            # cancel() may have run while we were awaiting create_subprocess_exec
            # — at that moment `self._proc` was still None, so cancel() returned
            # without signalling. Close the race by sending SIGTERM here.
            if self._cancelled:
                try:
                    proc.send_signal(signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass

            outcome: TaskOutcomeRecord | None = None
            peak_context_tokens: int = 0

            assert proc.stdout is not None
            # Default StreamReader limit is 64 KB; large MCP tool results (e.g. full
            # paper content or YouTube transcripts in a stream-json line) can exceed
            # even a generous limit and raise LimitOverrunError.  Use a manual
            # readline loop so we can catch and skip oversize lines instead of
            # crashing the whole runner.  In Python 3.12 the buffer IS consumed
            # before LimitOverrunError is raised, so `continue` is safe.
            proc.stdout._limit = 100 * 1024 * 1024
            while True:
                try:
                    raw_bytes = await proc.stdout.readline()
                except asyncio.LimitOverrunError as exc:
                    self._log.warning(
                        "stdout_line_overrun",
                        task_id=task.id,
                        consumed=exc.consumed,
                    )
                    continue
                if not raw_bytes:
                    break
                raw_line = raw_bytes.decode("utf-8", errors="replace").rstrip("\n")
                evt = self._coder.normalize_event(raw_line)
                if evt is None:
                    continue

                append_event(task_dir, evt)

                if evt.kind == "session_started":
                    self._log.info("agent_session_started")
                elif evt.kind == "tool_use":
                    self._log.info(
                        "agent_tool_use",
                        tool=evt.raw.get("tool_name") or evt.raw.get("name"),
                    )
                elif evt.kind == "session_ended":
                    self._log.info("agent_session_ended")

                if evt.kind == "rate_limit_info":
                    self._rate_gauge.update(evt)
                elif (
                    evt.usage is not None
                    and evt.kind != "session_ended"
                ):
                    prompt = _input_tokens(evt.usage)
                    if prompt > 0:
                        peak_context_tokens = max(peak_context_tokens, prompt)
                        threshold = (
                            self._coder.context_limit
                            * self._config.context_pressure_threshold_pct
                            / 100
                        )
                        if peak_context_tokens >= threshold:
                            task_log.log.warning(
                                "context_pressure_threshold_exceeded",
                                task_id=task.id,
                                peak_context_tokens=peak_context_tokens,
                                context_limit=self._coder.context_limit,
                                threshold_pct=self._config.context_pressure_threshold_pct,
                            )
                            cp_flag = task_dir / ".context_pressure"
                            cp_flag.touch()
                            try:
                                proc.send_signal(signal.SIGTERM)
                            except (ProcessLookupError, OSError):
                                pass
                            try:
                                await asyncio.wait_for(
                                    proc.wait(),
                                    timeout=float(SHUTDOWN_GRACE_SEC),
                                )
                            except asyncio.TimeoutError:
                                try:
                                    proc.send_signal(signal.SIGKILL)
                                except (ProcessLookupError, OSError):
                                    pass
                                await proc.wait()
                            break

                if (
                    evt.kind == "rate_limit"
                    and evt.rate_info is not None
                    and evt.rate_info.get("status") == "rejected"
                ):
                    resets_at = evt.rate_info.get("resets_at")
                    reason = (
                        f"rate_limit, sleep until {resets_at}"
                        if resets_at is not None
                        else "rate_limit"
                    )
                    task_log.log.warning(
                        "rate_limit_rejected",
                        task_id=task.id,
                        resets_at=resets_at,
                    )
                    self._queue.release(task.id, reason=reason)
                    try:
                        proc.send_signal(signal.SIGTERM)
                    except (ProcessLookupError, OSError):
                        pass
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        try:
                            proc.send_signal(signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            pass
                        await proc.wait()
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.RATE_LIMIT,
                        exit_code=proc.returncode,
                        reason=reason,
                        resets_at=resets_at,
                    )
                    break

            exit_code = await proc.wait()

            if outcome is None:
                cp_flag = task_dir / ".context_pressure"
                if cp_flag.exists():
                    cp_flag.unlink()
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.CONTEXT_PRESSURE,
                        exit_code=exit_code,
                        reason="context_pressure hook fired",
                    )
                elif self._killed:
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.KILLED,
                        exit_code=exit_code,
                        reason="manual_kill",
                    )
                elif self._cancelled:
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.FAILURE,
                        exit_code=exit_code,
                        reason="supervisor_shutdown",
                    )
                elif exit_code == 0:
                    blocked = False
                    try:
                        current = self._queue.get(task.id)
                        blocked = current.status == "blocked"
                    except Exception:
                        pass
                    if blocked:
                        outcome = TaskOutcomeRecord(
                            outcome=TaskOutcome.BLOCKED_BY_AGENT,
                            exit_code=exit_code,
                            reason="agent set task to blocked",
                        )
                    else:
                        outcome = TaskOutcomeRecord(
                            outcome=TaskOutcome.SUCCESS,
                            exit_code=exit_code,
                            reason="",
                        )
                else:
                    stderr_tail = _read_file_tail(stderr_path)
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.FAILURE,
                        exit_code=exit_code,
                        reason=f"subprocess exited with rc={exit_code}",
                        stderr_tail=stderr_tail,
                    )

            task_log.log.info(
                "subprocess_exited",
                task_id=task.id,
                exit_code=exit_code,
                outcome=outcome.outcome.value,
            )
            return outcome

    async def kill(self) -> None:
        """Mark as manually killed and terminate the subprocess."""
        self._killed = True
        await self.cancel()

    async def cancel(self) -> None:
        """Send SIGTERM to the child; escalate to SIGKILL after grace period."""
        self._cancelled = True
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.send_signal(signal.SIGTERM)
        except (ProcessLookupError, OSError):
            return
        try:
            await asyncio.wait_for(
                proc.wait(),
                timeout=float(SHUTDOWN_GRACE_SEC),
            )
        except asyncio.TimeoutError:
            try:
                proc.send_signal(signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            await proc.wait()


def _read_file_tail(path: Path, max_bytes: int = _STDERR_TAIL_BYTES) -> str | None:
    if not path.exists():
        return None
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", errors="replace")
