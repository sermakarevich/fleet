from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from fleet.core.launch import LaunchPlan
from fleet.core.task import Event, Task, TaskOutcomeRecord

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_HEADER_PATH = _TEMPLATES_DIR / "coder_header.md.tmpl"
_INSTRUCTION_FRESH_PATH = _TEMPLATES_DIR / "INSTRUCTION_FRESH.md"
_INSTRUCTION_CONTINUE_PATH = _TEMPLATES_DIR / "INSTRUCTION_CONTINUE.md"
_INSTRUCTION_VALIDATE_PATH = _TEMPLATES_DIR / "INSTRUCTION_VALIDATE.md"
_INSTRUCTION_RESEARCH_PATH = _TEMPLATES_DIR / "INSTRUCTION_RESEARCH.md"
_INSTRUCTION_DESIGN_PATH = _TEMPLATES_DIR / "INSTRUCTION_DESIGN.md"
_INSTRUCTION_COMMON_PATH = _TEMPLATES_DIR / "INSTRUCTION_COMMON.md"
_ISOLATED_PROTOCOL_PATH = _TEMPLATES_DIR / "ISOLATED_PROTOCOL.md"


def isolation_workdir(task_dir: Path) -> str | None:
    """The worktree an isolated task runs in, from task.json (legacy `.worktree` fallback)."""
    try:
        import json

        meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        if isinstance(meta, dict) and meta.get("worktree_path"):
            return str(meta["worktree_path"])
    except (OSError, ValueError):
        pass
    try:
        marker = task_dir / ".worktree"
        if marker.exists():
            return marker.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    return None


def _is_isolated(task_dir: Path) -> bool:
    """True when the task runs isolated: task.json names a worktree, or the
    legacy `.worktree` marker exists (even empty)."""
    return isolation_workdir(task_dir) is not None or (task_dir / ".worktree").exists()


def workdir_for(task: Task, task_dir: Path) -> str | None:
    """Directory the coder must work in: the isolated worktree when there is
    one, else the task's cwd, else None (fleet home, no directory flag).

    Every coder that passes a directory flag to its CLI (`opencode --dir`,
    `codex --cd`) must use this, never `task.cwd` directly: under isolation
    the subprocess is started inside the worktree, and a flag pointing at
    the original repo makes the model edit the shared tree instead.
    """
    return isolation_workdir(task_dir) or task.cwd


def render_prompt(
    task: Task, task_dir: Path, plan: LaunchPlan | None, *, mode: str | None = None
) -> str:
    """Build the one prompt every coder sends: header + pack + mode instructions.

    Shared by all five coders' `build_argv` so the assembly logic (header,
    launch-mode instructions, isolated-worktree protocol) exists once. *plan*
    is None for tests/back-compat call sites that don't plan launches yet;
    treated the same as a fresh, empty-pack plan. *mode* overrides
    `plan.mode` when given (the observer worker launches in "validate").
    """
    artifacts_dir = task_dir / "artifacts"
    worktree = isolation_workdir(task_dir)
    workdir = worktree or task.cwd
    invocation_line = f"Invocation directory: {workdir}" if workdir else ""
    header = (
        _HEADER_PATH.read_text(encoding="utf-8")
        .format(
            task_id=task.id,
            task_title=task.title,
            task_description=task.description or "",
            task_dir=task_dir,
            artifacts_dir=artifacts_dir,
            invocation_line=invocation_line,
        )
        .strip()
    )

    mode = mode or (plan.mode if plan is not None else "fresh")
    pack = plan.pack if plan is not None else ""

    if mode == "validate":
        mode_instructions = _INSTRUCTION_VALIDATE_PATH.read_text(encoding="utf-8").strip()
    elif mode == "research":
        mode_instructions = _INSTRUCTION_RESEARCH_PATH.read_text(encoding="utf-8").strip()
    elif mode == "design":
        mode_instructions = _INSTRUCTION_DESIGN_PATH.read_text(encoding="utf-8").strip()
    elif mode == "continue":
        mode_instructions = _INSTRUCTION_CONTINUE_PATH.read_text(encoding="utf-8").strip()
    else:
        mode_instructions = _INSTRUCTION_FRESH_PATH.read_text(encoding="utf-8").strip()
    common_instructions = _INSTRUCTION_COMMON_PATH.read_text(encoding="utf-8").strip()

    parts = [header]
    if pack:
        parts.append(pack)
    parts.append(mode_instructions)
    parts.append(common_instructions)
    if _is_isolated(task_dir):
        protocol = _ISOLATED_PROTOCOL_PATH.read_text(encoding="utf-8").strip()
        parts.append(protocol.replace("{worktree_path}", worktree or "your working directory"))

    return "\n\n---\n\n".join(parts)


class Coder(ABC):
    name: str
    context_limit: int = 200_000
    default_model: str = ""

    @classmethod
    def context_limit_for(
        cls, model: str | None, overrides: dict[str, int] | None = None
    ) -> int:
        """Context window for the given model string.

        Resolves through ``core.context_window.resolve_window`` with the
        class ``context_limit`` as the fallback, so supervisor and UI share
        one denominator. *overrides* is the parsed ``context_windows``
        config (``{model: tokens}``); None means the built-in table only.
        """
        from fleet.core.context_window import resolve_window

        return resolve_window(model, overrides, cls.context_limit)

    @abstractmethod
    def build_argv(
        self, task: Task, task_dir: Path, plan: LaunchPlan | None = None
    ) -> list[str]:
        """Return the argv list to spawn the coder CLI subprocess.

        *plan* is the `core.launch.LaunchPlan` for this attempt (fresh vs.
        continue, and the continue pack); None means "treat as fresh, no
        pack" for callers/tests that predate launch planning. Coders build
        their prompt via `render_prompt(task, task_dir, plan)`.
        """

    @abstractmethod
    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        """Return env-var overlay merged over os.environ when spawning.

        MUST include FLEET_TASK_ID, FLEET_TASK_DIR, FLEET_ARTIFACT_DIR.
        MUST NOT include ANTHROPIC_API_KEY (owned by the CLI).

        FLEET_ATTEMPT_N, FLEET_ATTEMPT_DIR, FLEET_LAUNCH_MODE are NOT this
        method's job — `workers/llm_session.py::LlmSession` layers those on
        top of this dict itself, since they depend on the attempt (not the
        coder), and adding them here would require every coder to widen its
        signature for values it never uses.
        """

    @abstractmethod
    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one line of subprocess stdout into a normalized Event.

        Returns None for malformed JSON or lines the coder wants to drop.
        SHALL be pure: no I/O, no logging, no side effects.
        """

    def write_runtime_config(self, project: Path, task: Task) -> None:
        """Inject coder-managed config (hooks, settings) into project root before spawn.

        Default is a no-op; coders that need to write config should override this.
        Called by LlmSession.run before the subprocess is spawned.
        """

    def probe_health(
        self, task: Task, task_dir: Path, since: datetime
    ) -> TaskOutcomeRecord | None:
        """Called periodically by LlmSession while the subprocess is silent.

        `since` is the time of the last stdout event: only provider errors
        logged after it count, because an error the CLI already recovered
        from (it kept streaming) must not kill a healthy session.
        Return a TaskOutcomeRecord to make the runner kill the process and
        report that outcome; None means healthy (or unsupported by this coder).
        Default is a no-op.
        """
        return None
