"""The coder contract and the task workspace every coder runs in.

:class:`Coder` is the interface one file per CLI in this package implements
(structural: a coder is any object with a ``spec`` plus ``build_argv``,
``env`` and ``normalize_event``). :class:`CoderSpec` is the frozen class-level
data (name, default model, fallback window); :func:`context_limit_for` is the
one place that resolves a per-model window from a spec. Optional hooks
(``write_runtime_config``, ``probe_health``) are NOT on the Protocol: callers
in ``workers`` look them up with ``getattr``. :class:`Workspace` owns where a
task runs (task dir, attempt dir, cwd, isolated worktree);
:func:`prompt_context` resolves the launch mode plus the ``prompts`` context
for ``build_argv``. Called by ``workers`` (spawn, stream, monitors) and the
coder modules.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fleet.core.context_window import resolve_window
from fleet.core.launch_policy import LaunchPlan
from fleet.core.task import Event, Task
from fleet.prompts import PromptContext

__all__ = [
    "Coder",
    "CoderSpec",
    "EventHandler",
    "Workspace",
    "FALLBACK_CONTEXT_LIMIT",
    "context_limit_for",
    "lookup_handler",
    "prompt_context",
]

FALLBACK_CONTEXT_LIMIT = 200_000
"""Window used when no coder (or no spec) is available: the legacy base default."""


EventHandler = Callable[[dict], Event | None]
"""One EVENT_MAP entry: parsed JSON line in, normalized Event (or None) out."""


def lookup_handler(
    table: dict[tuple[str, str | None], EventHandler],
    key: tuple[str, str | None],
) -> EventHandler | None:
    """Most-specific EVENT_MAP handler: (type, subtype), then (type, None).

    A ``result`` envelope stays a session end whatever its subtype is; a key
    with no entry at either level returns None.
    """
    handler = table.get(key)
    if handler is None and key[1] is not None:
        handler = table.get((key[0], None))
    return handler


@dataclass(frozen=True, slots=True)
class CoderSpec:
    """Class-level coder data: registry name, default model, fallback window."""

    name: str
    default_model: str
    context_limit: int


def context_limit_for(
    spec: CoderSpec, model: str | None, overrides: dict[str, int] | None = None
) -> int:
    """Context window for *model* under *spec* (one denominator for UI + supervisor).

    Resolves through ``core.context_window.resolve_window`` with the spec's
    ``context_limit`` as the fallback. *overrides* is the parsed
    ``context_windows`` config (``{model: tokens}``); None means built-ins only.
    """
    return resolve_window(model, overrides, spec.context_limit)


class Coder(Protocol):
    """The interface every coder CLI implements (spec, argv, env, events)."""

    spec: CoderSpec

    def build_argv(self, task: Task, task_dir: Path, plan: LaunchPlan | None = None) -> list[str]:
        """Return the argv list to spawn the coder CLI subprocess.

        *plan* is the `core.launch.LaunchPlan` for this attempt (fresh vs.
        continue, and the continue pack); None means "treat as fresh, no
        pack" for callers/tests that predate launch planning. Coders build
        their prompt via `prompts.render` (see `prompt_context` above).
        """
        ...

    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        """Return env-var overlay merged over os.environ when spawning.

        MUST include FLEET_TASK_ID, FLEET_TASK_DIR (see `coders.env.fleet_env`).
        MUST NOT include ANTHROPIC_API_KEY (owned by the CLI).

        FLEET_ATTEMPT_N, FLEET_ATTEMPT_DIR, FLEET_LAUNCH_MODE are NOT this
        method's job — `workers/llm_session.py::LlmSession` layers those on
        top of this dict itself, since they depend on the attempt (not the
        coder), and adding them here would require every coder to widen its
        signature for values it never uses.
        """
        ...

    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one line of subprocess stdout into a normalized Event.

        Returns None for malformed JSON or lines the coder wants to drop.
        SHALL be pure: no I/O, no logging, no side effects.
        """
        ...


@dataclass(frozen=True)
class Workspace:
    """Where a task runs: task dir, attempt dir, coder cwd, isolated worktree.

    The isolated worktree comes from ``task.json`` (``worktree_path``) with
    the legacy ``.worktree`` marker as fallback. ``attempt_dir`` is the
    current attempt's folder when the caller knows it, else None.
    """

    task_dir: Path
    cwd: str | None = None
    attempt_dir: Path | None = None

    @property
    def isolation_workdir(self) -> str | None:
        """The worktree an isolated task runs in, or None when not isolated."""
        try:
            meta = json.loads((self.task_dir / "task.json").read_text(encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("worktree_path"):
                return str(meta["worktree_path"])
        except (OSError, ValueError):
            pass
        try:
            marker = self.task_dir / ".worktree"
            if marker.exists():
                return marker.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
        return None

    @property
    def is_isolated(self) -> bool:
        """True when the task runs isolated (worktree named or marker present)."""
        return self.isolation_workdir is not None or (self.task_dir / ".worktree").exists()

    @property
    def workdir(self) -> str | None:
        """Directory the coder must work in: isolated worktree, else task cwd.

        Every coder that passes a directory flag to its CLI (``opencode
        --dir``, ``codex --cd``) must use this, never ``task.cwd`` directly:
        under isolation the subprocess starts inside the worktree, and a flag
        pointing at the original repo makes the model edit the shared tree.
        """
        return self.isolation_workdir or self.cwd


def prompt_context(
    task: Task, task_dir: Path, plan: LaunchPlan | None
) -> tuple[str, PromptContext]:
    """Launch mode plus the resolved ``prompts`` context for ``build_argv``.

    *plan* is None for callers that predate launch planning: treated as a
    fresh, empty-pack plan.
    """
    mode = plan.mode if plan is not None else "fresh"
    pack = plan.pack if plan is not None else ""
    workspace = Workspace(task_dir=task_dir, cwd=task.cwd)
    return mode, PromptContext(
        task=task,
        task_dir=task_dir,
        pack=pack,
        workdir=workspace.workdir,
        worktree=workspace.isolation_workdir,
        isolated=workspace.is_isolated,
    )
