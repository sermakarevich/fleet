"""Shared fixtures and utilities for fleet integration tests."""

from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path

import pytest
import structlog

from fleet.beads.client import BdError
from fleet.beads.queue import BeadsQueue, Queue
from fleet.coders.claude import ClaudeCoder
from fleet.core.config import RuntimeConfig
from fleet.core.job_ready import BeadSummary
from fleet.core.task import Task
from fleet.orchestrator import Supervisor, SupervisorState, default_services
from fleet.orchestrator.rate_gauge import RateGauge
from fleet.orchestrator.service import Service
from fleet.state import paths as state_paths
from fleet.state.config_file import load
from fleet.state.config_file import write as write_atomic

FAKE_CLAUDE_PY = Path(__file__).parent / "fake_cli" / "fake_claude.py"

BD_AVAILABLE: bool = shutil.which("bd") is not None


# ---------------------------------------------------------------------------
# FakeClaudeCoder
# ---------------------------------------------------------------------------


class FakeClaudeCoder:
    """Claude-shaped test double that runs fake_claude.py instead of the real CLI.

    Composes a real ClaudeCoder (event parsing, env, runtime config) and only
    swaps the spawned binary, so integration runs exercise the real coder
    logic. Subclasses may override env() for per-task scenarios.

    Args:
        scenario:  Default scenario for all runs.
        scenarios: Sequential list of scenarios; consumed one per call to env().
        fleet_home: Fleet fleet_home handed to the composed coder (defaults to the
            global one, exactly like the real coder used to resolve).
        **fake_env: Extra env vars forwarded to the subprocess.
    """

    spec = ClaudeCoder.spec

    def __init__(
        self,
        scenario: str = "clean_exit",
        scenarios: list[str] | None = None,
        fleet_home: Path | str | None = None,
        **fake_env: str,
    ) -> None:
        resolved = Path(fleet_home) if fleet_home is not None else state_paths.fleet_home()
        fleet_home = resolved
        self._cli = ClaudeCoder(fleet_home=fleet_home)
        self._scenario = scenario
        self._scenarios = scenarios
        self._fake_env = fake_env
        self._scenario_idx = 0

    @property
    def model(self) -> str:
        """The composed coder's model (used for spawn logging)."""
        return self._cli.model

    def build_argv(self, task: Task, task_dir: Path, plan=None) -> list[str]:
        parent_argv = self._cli.build_argv(task, task_dir)
        # Replace "claude" with "python fake_claude.py"; inherit all other args
        return ["python", str(FAKE_CLAUDE_PY)] + parent_argv[1:]

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        base = self._cli.env(task, task_dir)
        if self._scenarios and self._scenario_idx < len(self._scenarios):
            chosen = self._scenarios[self._scenario_idx]
            self._scenario_idx += 1
        else:
            chosen = self._scenario
        return {**base, "FAKE_CLAUDE_SCENARIO": chosen, **self._fake_env}

    def normalize_event(self, raw_line: str):
        """Parse one stdout line with the real Claude event logic."""
        return self._cli.normalize_event(raw_line)

    def write_runtime_config(self, project: Path, task: object) -> None:
        """Install the real Claude project hooks and settings."""
        self._cli.write_runtime_config(project, task)


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
        self._ignores: dict[str, str] = {}
        self._children: dict[str, list[BeadSummary]] = {}
        self._isolation: dict[str, dict] = {}
        self._meta: dict[str, dict] = {}
        self._listeners: list[Callable[[str, str], None]] = []

    def add_task(self, task: Task) -> None:
        self._tasks[task.id] = task

    def add_listener(self, cb: Callable[[str, str], None]) -> None:
        """Register callback(method_name, task_id) called after each state change."""
        self._listeners.append(cb)

    def _fire(self, method: str, task_id: str) -> None:
        for cb in self._listeners:
            cb(method, task_id)

    def claim(self, task_id: str, claimer_id: str) -> Task:
        """Move one open task to in_progress (the single claim path)."""
        _ = claimer_id
        task = self.get(task_id)
        updated = replace(task, status="in_progress")
        self._tasks[task_id] = updated
        self.claims.append(task_id)
        self._fire("claim", task_id)
        return updated

    def claim_next(
        self,
        claimer_id: str,
        *,
        can_claim: Callable[[str | None], bool] | None = None,
    ) -> Task | None:
        _ = claimer_id
        for tid, t in list(self._tasks.items()):
            if t.status == "open":
                if can_claim is not None and not can_claim(t.coder):
                    continue
                return self.claim(tid, claimer_id)
        return None

    def release(self, task_id: str, reason: str = "", wait_sec: int = 0) -> None:
        self.released.append((task_id, reason))
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="open")
        self._fire("release", task_id)

    def set_blocked(self, task_id: str, reason: str) -> None:
        self.blocked.append((task_id, reason))
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="blocked")
        self._fire("set_blocked", task_id)

    def set_ignore(self, task_id: str, until: str) -> None:
        self._ignores[task_id] = until
        self._fire("set_ignore", task_id)

    def clear_ignore(self, task_id: str) -> None:
        self._ignores.pop(task_id, None)
        self._fire("clear_ignore", task_id)

    def set_overrides(
        self,
        task_id: str,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        isolation: str | None = None,
        job_gate: str | None = None,
    ) -> None:
        if task_id in self._tasks:
            t = self._tasks[task_id]
            self._tasks[task_id] = replace(
                t,
                coder=coder if coder is not None else t.coder,
                model=model if model is not None else t.model,
                worker=worker if worker is not None else t.worker,
                isolation=isolation if isolation is not None else t.isolation,
                job_gate=job_gate if job_gate is not None else t.job_gate,
            )

    def close(self, task_id: str, reason: str = "completed") -> None:
        self.closed.append((task_id, reason))
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], status="closed")
        self._fire("close", task_id)

    def delete(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)
        self._fire("delete", task_id)

    def comment(self, task_id: str, body: str) -> None:
        self.comments.append((task_id, body))
        self._fire("comment", task_id)

    def get(self, task_id: str) -> Task:
        if task_id not in self._tasks:
            raise BdError(f"Task {task_id} not found")
        return self._tasks[task_id]

    def list_ready(self, limit: int = 50) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == "open"][:limit]

    def list_in_progress(self, limit: int = 50) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == "in_progress"][:limit]

    def list_blocked(self, limit: int = 100) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == "blocked"][:limit]

    def freeze_coder_model(self, task_id: str, coder: str, model: str) -> None:
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], coder=coder, model=model)

    def set_bd_fields(self, task_id: str, body: dict) -> None:
        t = self._tasks.get(task_id)
        if t is None:
            return
        self._tasks[task_id] = replace(
            t,
            title=body.get("title", t.title),
            description=body.get("description", t.description),
            status=body.get("status", t.status),
        )

    def create_task(  # noqa: PLR0913, PLR0917  # mirrors Queue.create_task signature
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        worker: str | None = None,
        extra_args: str | None = None,
    ) -> Task:
        _ = (depends_on, labels)
        task_id = f"mem-{len(self._tasks):03d}"
        task = Task(
            id=task_id,
            title=title,
            description=description,
            status="open",
            cwd=cwd,
            coder=coder,
            model=model,
            worker=worker,
        )
        self._tasks[task_id] = task
        self._meta[task_id] = _metadata_of(extra_args)
        return task

    def create_child(self, epic_id: str, spec: dict) -> Task:
        """Open one child bead under an epic and link it."""
        epic = self.get(epic_id)
        child = self.create_task(
            spec.get("title") or epic.title,
            description=spec.get("body") or "",
            cwd=spec.get("cwd") or epic.cwd,
            coder=spec.get("coder") or epic.coder,
            model=spec.get("model") or epic.model,
        )
        self._children.setdefault(epic_id, []).append(BeadSummary(id=child.id, status="open"))
        return child

    def list_children(self, epic_id: str) -> list[BeadSummary]:
        """List an epic's child beads with their statuses."""
        return list(self._children.get(epic_id, []))

    def list_ignored(self, limit: int = 100) -> list[tuple[Task, str]]:
        """List blocked tasks whose triage ignore is still recorded."""
        rows = [
            (self._tasks[tid], until) for tid, until in self._ignores.items() if tid in self._tasks
        ]
        return rows[:limit]

    def list_by_metadata(self, field: str, value: str) -> list[Task]:
        """Tasks whose recorded `--metadata` JSON has `field` equal to `value`."""
        return [
            task
            for task_id, task in self._tasks.items()
            if self._meta.get(task_id, {}).get(field) == value
        ]

    def set_cwd(self, task_id: str, cwd: str) -> None:
        """Persist the invocation cwd for a task."""
        if task_id in self._tasks:
            self._tasks[task_id] = replace(self._tasks[task_id], cwd=cwd)

    def set_isolation_info(
        self, task_id: str, repo_root: str, base_ref: str, worktree_path: str
    ) -> None:
        """Persist git isolation info for a task."""
        self._isolation[task_id] = {
            "repo_root": repo_root,
            "base_ref": base_ref,
            "worktree_path": worktree_path,
        }

    def read_isolation_info(self, task_id: str) -> dict | None:
        """Return git isolation info, or None when not isolated."""
        return self._isolation.get(task_id)

    def clear_isolation_info(self, task_id: str) -> None:
        """Drop git isolation info after merge/cleanup."""
        self._isolation.pop(task_id, None)


# ---------------------------------------------------------------------------
# Beads helper
# ---------------------------------------------------------------------------


def _metadata_of(extra_args: str | None) -> dict:
    """Parse the `--metadata <json>` payload out of a create extra_args string."""
    if not extra_args:
        return {}
    try:
        tokens = shlex.split(extra_args)
        raw = tokens[tokens.index("--metadata") + 1]
        parsed = json.loads(raw)
    except (ValueError, IndexError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _git_init(path: Path) -> None:
    """Create a minimal git repo at path (needed by beads)."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@test.com",
            "-c",
            "user.name=test",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        cwd=path,
        capture_output=True,
        check=True,
    )


def init_beads_queue(tmp_path: Path):  # type: ignore[return]
    """Initialize a git repo + beads workspace in tmp_path and return a BeadsQueue."""

    _git_init(tmp_path)
    result = subprocess.run(["bd", "init"], cwd=tmp_path, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"bd init failed: {result.stderr.decode()}")
    return BeadsQueue(tmp_path)


def beads_functional() -> bool:
    """Return True if bd can initialize and run basic commands in a fresh git repo."""
    if not BD_AVAILABLE:
        return False

    with tempfile.TemporaryDirectory() as d:
        path = Path(d)
        try:
            _git_init(path)
            r = subprocess.run(["bd", "init"], cwd=path, capture_output=True, check=False)
            if r.returncode != 0:
                return False
            # Verify a basic bd command works
            r2 = subprocess.run(
                ["bd", "ready", "--json"], cwd=path, capture_output=True, check=False
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
    coder: ClaudeCoder | FakeClaudeCoder | None = None,
    config: RuntimeConfig | None = None,
) -> Supervisor:
    """Create a Supervisor wired to tmp_path with optional config override."""
    runtime_toml = tmp_path / ".fleet" / "runtime.toml"
    if config is not None:
        runtime_toml.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(runtime_toml, {k: str(v) for k, v in asdict(config).items()})
    else:
        config = load(runtime_toml)
    log = structlog.get_logger()
    pin = coder or FakeClaudeCoder(fleet_home=tmp_path)
    state = SupervisorState(
        config=config,
        fleet_home=tmp_path,
        runtime_toml_path=runtime_toml,
        queue=queue,
        log=log,
        rate_gauge=RateGauge(log=log),
        coder_factory=lambda name, model: pin,
    )
    services = default_services()
    fast: list[Service] = []
    for svc in services:
        adjusted = svc
        if getattr(svc, "name", "") in ("claim", "config_reload") and hasattr(svc, "interval_sec"):
            if is_dataclass(svc) and not isinstance(svc, type):
                # Frozen PeriodicService instances are replaced, not mutated.
                adjusted = replace(svc, interval_sec=1)
            else:
                svc.interval_sec = 1
        fast.append(adjusted)
    return Supervisor(state=state, services=fast, shutdown_grace_sec=3)


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
    except TimeoutError:
        pass
    finally:
        await supervisor._shutdown()
        try:
            await asyncio.wait_for(sup_task, timeout=5.0)
        except TimeoutError:
            sup_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await sup_task


@pytest.fixture(autouse=True)
def _fast_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch worker/runner constants to fast values for all integration tests.

    Orchestrator service intervals and the supervisor grace window are set
    per-service in make_supervisor above, not patched here.
    """
    monkeypatch.setattr("fleet.core.retry_policy.RATE_LIMIT_DEFAULT_SLEEP_SEC", 0)
    monkeypatch.setattr("fleet.workers.llm_session.SHUTDOWN_GRACE_SEC", 3)


def fast_config(**overrides: object) -> RuntimeConfig:
    """RuntimeConfig with surviving fields only; poll/grace intervals are now constants.

    Compaction is off by default: integration tests drive FakeClaudeCoder and
    must never spawn the real compaction CLI (network, slow, flaky). Unit
    tests in tests/workers/test_compact.py cover the Compact step itself.
    """
    defaults: dict = {"compaction_enabled": False}
    defaults.update(overrides)
    return RuntimeConfig(**defaults)  # type: ignore[arg-type]
