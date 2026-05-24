"""Shared fixtures and utilities for fleet integration tests."""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from typing import Callable

import structlog

from fleet.coders.claude import ClaudeCoder
from fleet.config import write_atomic
from fleet.queue import Queue
from fleet.schemas import RuntimeConfig, Task
from fleet.supervisor import Supervisor

FAKE_CLAUDE_PY = Path(__file__).parent / "fake_cli" / "fake_claude.py"

BD_AVAILABLE: bool = shutil.which("bd") is not None


# ---------------------------------------------------------------------------
# FakeClaudeCoder
# ---------------------------------------------------------------------------


class FakeClaudeCoder(ClaudeCoder):
    """ClaudeCoder that runs fake_claude.py instead of the real 'claude' CLI.

    All event normalization, env(), and other coder logic is inherited.
    Only build_argv is overridden to substitute the fake script.

    Args:
        scenario:  Default scenario for all runs.
        scenarios: Sequential list of scenarios; consumed one per call to env().
        **fake_env: Extra env vars forwarded to the subprocess.
    """

    def __init__(
        self,
        scenario: str = "clean_exit",
        scenarios: list[str] | None = None,
        **fake_env: str,
    ) -> None:
        super().__init__()
        self._scenario = scenario
        self._scenarios = scenarios
        self._fake_env = fake_env
        self._scenario_idx = 0

    def build_argv(self, task: Task, task_dir: Path) -> list[str]:
        parent_argv = super().build_argv(task, task_dir)
        # Replace "claude" with "python fake_claude.py"; inherit all other args
        return ["python", str(FAKE_CLAUDE_PY)] + parent_argv[1:]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        base = super().env(task, task_dir)
        if self._scenarios and self._scenario_idx < len(self._scenarios):
            chosen = self._scenarios[self._scenario_idx]
            self._scenario_idx += 1
        else:
            chosen = self._scenario
        return {**base, "FAKE_CLAUDE_SCENARIO": chosen, **self._fake_env}


# ---------------------------------------------------------------------------
# MemoryQueue — in-memory stub
# NOTE: does NOT provide real beads atomicity; use BeadsQueue for FR-04 tests
# ---------------------------------------------------------------------------


class MemoryQueue(Queue):
    """In-memory queue stub that tracks all state changes for test assertions."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self.released: list[tuple[str, str]] = []
        self.blocked: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.closed: list[tuple[str, str]] = []
        self.claims: list[str] = []
        self._listeners: list[Callable[[str, str], None]] = []

    def add_task(self, task: Task) -> None:
        self._tasks[task.id] = task

    def add_listener(self, cb: Callable[[str, str], None]) -> None:
        """Register callback(method_name, task_id) called after each state change."""
        self._listeners.append(cb)

    def _fire(self, method: str, task_id: str) -> None:
        for cb in self._listeners:
            cb(method, task_id)

    def claim_next(self, claimer_id: str) -> Task | None:
        for tid, t in list(self._tasks.items()):
            if t.status == "open":
                updated = replace(t, status="in_progress")
                self._tasks[tid] = updated
                self.claims.append(tid)
                self._fire("claim", tid)
                return updated
        return None

    def release(self, task_id: str, reason: str = "") -> None:
        self.released.append((task_id, reason))
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="open")
        self._fire("release", task_id)

    def set_blocked(self, task_id: str, reason: str) -> None:
        self.blocked.append((task_id, reason))
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="blocked")
        self._fire("set_blocked", task_id)

    def close(self, task_id: str, reason: str = "completed") -> None:
        self.closed.append((task_id, reason))
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="closed")
        self._fire("close", task_id)

    def comment(self, task_id: str, body: str) -> None:
        self.comments.append((task_id, body))
        self._fire("comment", task_id)

    def get(self, task_id: str) -> Task:
        if task_id not in self._tasks:
            from fleet.queue import BeadsError
            raise BeadsError(f"Task {task_id} not found")
        return self._tasks[task_id]

    def list_ready(self, limit: int = 50) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == "open"][:limit]

    def list_in_progress(self, limit: int = 50) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == "in_progress"][:limit]

    def freeze_coder_model(self, task_id: str, coder: str, model: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], coder=coder, model=model)

    def create_task(
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
    ) -> Task:
        task_id = f"mem-{len(self._tasks):03d}"
        task = Task(id=task_id, title=title, description=description, status="open", cwd=cwd, coder=coder, model=model)
        self._tasks[task_id] = task
        return task


# ---------------------------------------------------------------------------
# Beads helper
# ---------------------------------------------------------------------------


def _git_init(path: Path) -> None:
    """Create a minimal git repo at path (needed by beads)."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test",
         "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def init_beads_queue(tmp_path: Path):  # type: ignore[return]
    """Initialize a git repo + beads workspace in tmp_path and return a BeadsQueue."""
    from fleet.queue import BeadsQueue

    _git_init(tmp_path)
    result = subprocess.run(["bd", "init"], cwd=tmp_path, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"bd init failed: {result.stderr.decode()}")
    return BeadsQueue(tmp_path)


def beads_functional() -> bool:
    """Return True if bd can initialize and run basic commands in a fresh git repo."""
    if not BD_AVAILABLE:
        return False
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        path = Path(d)
        try:
            _git_init(path)
            r = subprocess.run(["bd", "init"], cwd=path, capture_output=True)
            if r.returncode != 0:
                return False
            # Verify a basic bd command works
            r2 = subprocess.run(
                ["bd", "ready", "--json"], cwd=path, capture_output=True
            )
            return r2.returncode == 0
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Supervisor factory
# ---------------------------------------------------------------------------


def make_supervisor(
    tmp_path: Path,
    queue: Queue,
    coder: ClaudeCoder | None = None,
    config: RuntimeConfig | None = None,
) -> Supervisor:
    """Create a Supervisor wired to tmp_path with optional config override."""
    runtime_toml = tmp_path / ".fleet" / "runtime.toml"
    if config is not None:
        runtime_toml.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(runtime_toml, {k: str(v) for k, v in asdict(config).items()})
    return Supervisor(
        coder=coder or FakeClaudeCoder(),
        queue=queue,
        runtime_toml_path=runtime_toml,
        project_root=tmp_path,
        log=structlog.get_logger(),
    )


# ---------------------------------------------------------------------------
# Test runner helper
# ---------------------------------------------------------------------------


async def run_until(
    supervisor: Supervisor,
    done: asyncio.Event,
    timeout: float = 15.0,
) -> None:
    """Run supervisor in the background; shutdown after `done` fires or timeout."""
    sup_task = asyncio.create_task(supervisor.run())
    try:
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        await supervisor._shutdown()
        try:
            await asyncio.wait_for(sup_task, timeout=5.0)
        except asyncio.TimeoutError:
            sup_task.cancel()
            try:
                await sup_task
            except (asyncio.CancelledError, Exception):
                pass


def fast_config(**overrides: object) -> RuntimeConfig:
    """RuntimeConfig with short poll intervals suitable for integration tests."""
    base: dict = dict(
        claim_poll_interval_sec=1,
        config_poll_interval_sec=1,
        shutdown_grace_sec=3,
        rate_limit_default_sleep_sec=0,
    )
    base.update(overrides)
    return RuntimeConfig(**base)  # type: ignore[arg-type]
