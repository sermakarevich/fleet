from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import structlog

from fleet.coders.base import Coder
from fleet.core.config import RuntimeConfig
from fleet.core.limits import PROBE_INTERVAL_SEC, PROBE_SILENCE_SEC, SHUTDOWN_GRACE_SEC
from fleet.core.task import Event, Task, TaskOutcome, TaskOutcomeRecord
from fleet.logging import append_event, open_task_log
from fleet.state.paths import task_dir as _task_dir

_STDERR_TAIL_BYTES = 2048

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _signal_group(proc: asyncio.subprocess.Process, sig: int) -> None:
    """Signal the child's whole process group; fall back to the child alone."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass


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
    """Spawns the coder subprocess, streams stdout, classifies the exit.

    Makes no queue calls: it returns a ``TaskOutcomeRecord`` describing what
    happened (exit code, rate limit, kill reason, ...) and leaves the caller
    (``orchestrator/reap.py``) to consult bead status and drive the queue.
    """

    def __init__(
        self,
        task: Task,
        coder: Coder,
        config: RuntimeConfig,
        rate_gauge: RateGauge,
        project_root: Path,
        fleet_home: Path,
        log: structlog.BoundLogger,
    ) -> None:
        self._task = task
        self._coder = coder
        self._config = config
        self._rate_gauge = rate_gauge
        self._project_root = project_root
        self._fleet_home = fleet_home
        self._log = log
        self._proc: asyncio.subprocess.Process | None = None
        self._cancelled = False
        self._killed = False
        self._kill_reason = "manual_kill"

    async def run(self) -> TaskOutcomeRecord:
        task = self._task

        task_dir = _task_dir(self._fleet_home, task.id)
        artifacts_dir = task_dir / "artifacts"
        task_dir.mkdir(parents=True, exist_ok=True)
        _ensure_artifact_stubs(artifacts_dir, task.id)
        self._coder.write_runtime_config(self._project_root, task)

        with open_task_log(task_dir, task.id) as task_log:
            stderr_path = Path(task_log.stderr_file.name)

            argv = self._coder.build_argv(task, task_dir)
            extra_env = self._coder.env(task, task_dir)
            proc_env = {**os.environ, **extra_env}
            if "BEADS_DIR" not in proc_env:
                proc_env["BEADS_DIR"] = str(self._fleet_home / ".beads")

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
                start_new_session=True,
            )
            self._proc = proc
            started_at = datetime.now(tz=UTC)
            run_file = task_dir / "run.json"
            run_data: dict = {}
            try:
                try:
                    pgid = os.getpgid(proc.pid)
                except OSError:
                    pgid = proc.pid
                run_data = {
                    "pid": proc.pid,
                    "pgid": pgid,
                    "started_at": started_at.isoformat(),
                    "coder": self._coder.__class__.__name__,
                }
                tmp = run_file.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(run_data), encoding="utf-8")
                tmp.replace(run_file)
            except OSError as exc:
                self._log.warning("run_file_write_failed", error=str(exc))

            # cancel() may have run while we were awaiting create_subprocess_exec
            # — at that moment `self._proc` was still None, so cancel() returned
            # without signalling. Close the race by sending SIGTERM here.
            if self._cancelled:
                _signal_group(proc, signal.SIGTERM)

            outcome: TaskOutcomeRecord | None = None
            peak_context_tokens: int = 0
            last_logged_bucket: int = -1
            _logged_session_started = False

            assert proc.stdout is not None
            # Default StreamReader limit is 64 KB; large MCP tool results (e.g. full
            # paper content or YouTube transcripts in a stream-json line) can exceed
            # even a generous limit and raise LimitOverrunError.  Use a manual
            # readline loop so we can catch and skip oversize lines instead of
            # crashing the whole runner.  In Python 3.12 the buffer IS consumed
            # before LimitOverrunError is raised, so `continue` is safe.
            proc.stdout._limit = 100 * 1024 * 1024
            last_event_at = started_at
            last_probe_at = started_at
            while True:
                try:
                    raw_bytes = await asyncio.wait_for(
                        proc.stdout.readline(), timeout=PROBE_INTERVAL_SEC
                    )
                except TimeoutError:
                    now = datetime.now(tz=UTC)
                    silent_for = (now - last_event_at).total_seconds()
                    since_last_probe = (now - last_probe_at).total_seconds()
                    if silent_for <= PROBE_SILENCE_SEC or since_last_probe < PROBE_INTERVAL_SEC:
                        continue
                    last_probe_at = now
                    probe_outcome = await asyncio.to_thread(
                        self._coder.probe_health, task, task_dir, started_at
                    )
                    if probe_outcome is None:
                        continue
                    task_log.log.warning(
                        "provider_error_detected",
                        task_id=task.id,
                        reason=probe_outcome.reason,
                    )
                    _signal_group(proc, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except TimeoutError:
                        _signal_group(proc, signal.SIGKILL)
                        await proc.wait()
                    outcome = probe_outcome
                    break
                except asyncio.LimitOverrunError as exc:
                    self._log.warning(
                        "stdout_line_overrun",
                        task_id=task.id,
                        consumed=exc.consumed,
                    )
                    continue
                if not raw_bytes:
                    break
                last_event_at = datetime.now(tz=UTC)
                raw_line = raw_bytes.decode("utf-8", errors="replace").rstrip("\n")
                evt = self._coder.normalize_event(raw_line)
                if evt is None:
                    continue

                append_event(task_dir, evt)

                if evt.kind == "session_started" and not _logged_session_started:
                    _logged_session_started = True
                    self._log.info("agent_session_started")
                elif evt.kind == "tool_use":
                    self._log.info(
                        "agent_tool_use",
                        tool=evt.tool_name
                        or evt.raw.get("tool_name")
                        or evt.raw.get("name"),
                    )
                elif evt.kind == "session_ended":
                    self._log.info("agent_session_ended")

                if evt.kind == "rate_limit_info":
                    self._rate_gauge.update(evt)
                elif evt.usage is not None and evt.kind != "session_ended":
                    prompt = _input_tokens(evt.usage)
                    if prompt > 0:
                        peak_context_tokens = max(peak_context_tokens, prompt)
                        pct = peak_context_tokens / self._coder.context_limit * 100
                        bucket = int(pct // 10)
                        if bucket > last_logged_bucket:
                            task_log.log.info(
                                "context_usage",
                                task_id=task.id,
                                context_tokens=peak_context_tokens,
                                context_limit=self._coder.context_limit,
                                pct=round(pct, 1),
                            )
                            last_logged_bucket = bucket

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
                    _signal_group(proc, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except TimeoutError:
                        _signal_group(proc, signal.SIGKILL)
                        await proc.wait()
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.RATE_LIMIT,
                        exit_code=proc.returncode,
                        reason=reason,
                        resets_at=resets_at,
                    )
                    break

            exit_code = await proc.wait()
            try:
                run_data["exit_code"] = exit_code
                run_data["ended_at"] = datetime.now(tz=UTC).isoformat()
                tmp = run_file.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(run_data), encoding="utf-8")
                tmp.replace(run_file)
            except OSError as exc:
                self._log.warning("run_file_write_failed", error=str(exc))

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
                        reason=self._kill_reason,
                    )
                elif self._cancelled:
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.FAILURE,
                        exit_code=exit_code,
                        reason="supervisor_shutdown",
                    )
                elif exit_code == 0:
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

    async def kill(self, reason: str = "manual_kill") -> None:
        """Mark as manually killed and terminate the subprocess."""
        self._killed = True
        self._kill_reason = reason
        await self.cancel()

    async def cancel(self) -> None:
        """Send SIGTERM to the child; escalate to SIGKILL after grace period."""
        self._cancelled = True
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        _signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(
                proc.wait(),
                timeout=float(SHUTDOWN_GRACE_SEC),
            )
        except TimeoutError:
            _signal_group(proc, signal.SIGKILL)
            await proc.wait()


def _read_file_tail(path: Path, max_bytes: int = _STDERR_TAIL_BYTES) -> str | None:
    if not path.exists():
        return None
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        return f.read().decode("utf-8", errors="replace")
