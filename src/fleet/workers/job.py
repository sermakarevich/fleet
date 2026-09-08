"""The `job` family: research, design, gate, spawn, then observe.

A bead of type `epic` with metadata ``fleet_worker=job`` (``fleet bd
create --worker job``) decomposes itself instead of being decomposed by a
human: ``plan_job`` reads the task directory into a ``core/job_phase``
snapshot and picks one phase worker per attempt (``job.research``,
``job.design``, ``job.gate``, ``job.spawn``, ``job.observe``), so the
Attempts timeline shows the job's history. After research and design the
model writes RESULT.json ``status=partial`` (next_step design/gate); the
policy releases and the supervisor re-claims into the next phase. The
observe phase reuses the observer steps from ``workers/observe.py``.

The job worker creates beads; it never runs workers — only the
orchestrator runs workers.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fleet.core.job_phase import JobSnapshot, phase, phase_failures
from fleet.core.job_plan import validate_tasks
from fleet.core.launch import LaunchPlan
from fleet.core.task import TaskOutcome, TaskOutcomeRecord
from fleet.state import attempts as state_attempts

from .base import StepContext, StepResult, Worker
from .llm_session import LlmSession
from .observe import CollectChildren, SpawnFollowups, WaitChildren

# artifacts/RESEARCH.md cap the research prompt enforces (also truncates reads).
RESEARCH_MAX_BYTES = 12 * 1024
# Design pack caps: operator notes and validation errors are bounded inputs.
DESIGN_NOTES_MAX_CHARS = 4 * 1024
DESIGN_ERRORS_MAX_CHARS = 4 * 1024
# ask_human context disambiguating the gate question from triage questions.
JOB_GATE_CONTEXT = "job_gate"

GATE_OPTION_APPROVE = "approve"
GATE_OPTION_REVISE = "revise (write note)"
GATE_OPTION_CANCEL = "cancel job"
GATE_OPTIONS = [GATE_OPTION_APPROVE, GATE_OPTION_REVISE, GATE_OPTION_CANCEL]

QueueFactory = Callable[[Path], Any]
StoreFactory = Callable[[Path], Any]


def _default_queue(home: Path) -> Any:
    from fleet.beads.queue import BeadsQueue

    return BeadsQueue(home)


def _default_store(_home: Path) -> Any:
    """The ask_human store, same pattern as the triage loop (default DB)."""
    from fleet.integrations.ask_human.store import QuestionStore

    return QuestionStore()


def _ensure_artifact_stubs(artifacts_dir: Path, task_id: str) -> None:
    """Create PLAN.md, HANDOFF.md, KNOWLEDGE.md stubs and outputs/ if missing."""
    from .task import _ensure_artifact_stubs as _seed

    _seed(artifacts_dir, task_id)


def _rotate_result(artifacts_dir: Path) -> None:
    """Move a previous attempt's RESULT.json aside so it can't leak forward."""
    result_file = artifacts_dir / "RESULT.json"
    if result_file.exists():
        result_file.replace(artifacts_dir / "RESULT.prev.json")


def _write_result(
    artifacts_dir: Path,
    *,
    status: str,
    summary: str,
    next_step: str = "",
    blocked_reason: str = "",
) -> None:
    """Write artifacts/RESULT.json for a Python-decided gate/spawn outcome."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"schema": 1, "status": status, "summary": summary}
    if next_step:
        payload["next_step"] = next_step
    if blocked_reason:
        payload["blocked_reason"] = blocked_reason
    (artifacts_dir / "RESULT.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def _read_text_capped(path: Path, cap: int) -> str | None:
    try:
        return path.read_text(encoding="utf-8")[:cap]
    except OSError:
        return None


def _load_tasks_doc(task_dir: Path) -> tuple[Any, str | None]:
    """Return (parsed tasks.json, error); error is None on success."""
    try:
        text = (task_dir / "artifacts" / "tasks.json").read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read tasks.json: {exc}"
    try:
        return json.loads(text), None
    except ValueError as exc:
        return None, f"tasks.json is not valid JSON: {exc}"


def _task_titles(doc: Any) -> list[str]:
    tasks = doc.get("tasks") if isinstance(doc, dict) else None
    if not isinstance(tasks, list):
        return []
    return [str(t.get("title") or t.get("key") or "?") for t in tasks if isinstance(t, dict)]


class JobPrepare:
    """Seed stubs, rotate stale RESULT.json, set the research/design launch pack."""

    name = "job_prepare"

    def __init__(self, mode: str) -> None:
        assert mode in ("research", "design")
        self._mode = mode

    async def run(self, ctx: StepContext) -> StepResult:
        artifacts_dir = ctx.task_dir / "artifacts"
        _ensure_artifact_stubs(artifacts_dir, ctx.task.id)
        _rotate_result(artifacts_dir)
        if self._mode == "design":
            parts = []
            research = _read_text_capped(artifacts_dir / "RESEARCH.md", RESEARCH_MAX_BYTES)
            if research:
                parts.append(f"# RESEARCH.md\n\n{research}")
            notes = _read_text_capped(artifacts_dir / "DESIGN_NOTES.md", DESIGN_NOTES_MAX_CHARS)
            if notes:
                parts.append(f"# Operator revision notes\n\n{notes}")
            errors = _read_text_capped(
                artifacts_dir / "DESIGN_ERRORS.md", DESIGN_ERRORS_MAX_CHARS
            )
            if errors:
                parts.append(f"# Previous validation errors (fix these)\n\n{errors}")
            pack = "\n\n---\n\n".join(parts)
        else:
            pack = ""
        plan = LaunchPlan(
            mode=self._mode, pack=pack, pack_bytes=len(pack.encode("utf-8")),
            needs_compaction=False,
        )
        ctx.scratch["launch_plan"] = plan
        attempt_dir = ctx.attempt_dir or ctx.task_dir
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "launch.json").write_text(
            json.dumps({"mode": self._mode, "pack_bytes": plan.pack_bytes, "kind": "work"}),
            encoding="utf-8",
        )
        assert ctx.coder is not None
        ctx.coder.write_runtime_config(ctx.project_root, ctx.task)
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


class AskApproval:
    """Human gate between design and spawn (non-blocking ask_human question)."""

    name = "ask_approval"

    def __init__(self, store_factory: StoreFactory | None = None) -> None:
        self._store_factory = store_factory or _default_store

    def _invalid_plan(
        self, ctx: StepContext, errors: list[str]
    ) -> StepResult:
        """Send an invalid plan back to design without asking the operator."""
        artifacts_dir = ctx.task_dir / "artifacts"
        (artifacts_dir / "DESIGN_ERRORS.md").write_text(
            "# tasks.json validation errors\n\n" + "\n".join(f"- {e}" for e in errors) + "\n",
            encoding="utf-8",
        )
        _write_result(
            artifacts_dir, status="partial",
            summary="tasks.json invalid; see DESIGN_ERRORS.md",
            next_step="design",
        )
        return StepResult(status="ok")

    async def run(self, ctx: StepContext) -> StepResult:
        artifacts_dir = ctx.task_dir / "artifacts"
        _rotate_result(artifacts_dir)
        doc, load_error = _load_tasks_doc(ctx.task_dir)
        if load_error is not None:
            return self._invalid_plan(ctx, [load_error])
        max_children = getattr(ctx.config, "job_max_children", 30)
        errors = validate_tasks(doc, max_children=max_children)
        if errors:
            return self._invalid_plan(ctx, errors)
        store = self._store_factory(ctx.fleet_home)
        try:
            answered = store.fetch_answered_for_task(ctx.task.id, JOB_GATE_CONTEXT)
        except Exception as exc:  # noqa: BLE001 - step contract: return fail, never raise
            return StepResult(status="fail", reason=f"cannot read gate answers: {exc}")
        if answered:
            question = answered[-1]
            return self._apply_answer(ctx, question)
        try:
            pending = store.fetch_pending_for_task(ctx.task.id, JOB_GATE_CONTEXT)
        except Exception as exc:  # noqa: BLE001 - step contract
            return StepResult(status="fail", reason=f"cannot read gate questions: {exc}")
        if pending:
            return StepResult(
                status="outcome",
                outcome=TaskOutcomeRecord(
                    outcome=TaskOutcome.WAITING,
                    reason="waiting for job gate approval",
                ),
            )
        titles = _task_titles(doc)
        prompt = f"Job {ctx.task.id}: approve {len(titles)} tasks?\n" + "\n".join(
            f"- {t}" for t in titles
        )
        try:
            store.ask(
                prompt, list(GATE_OPTIONS),
                task_id=ctx.task.id, context=JOB_GATE_CONTEXT, agent_id="job",
            )
        except Exception as exc:  # noqa: BLE001 - step contract
            return StepResult(status="fail", reason=f"cannot ask gate question: {exc}")
        return StepResult(
            status="outcome",
            outcome=TaskOutcomeRecord(
                outcome=TaskOutcome.WAITING,
                reason="waiting for job gate approval",
            ),
        )

    def _apply_answer(self, ctx: StepContext, question: dict) -> StepResult:
        """Apply the operator's gate answer: approve, revise, or cancel."""
        artifacts_dir = ctx.task_dir / "artifacts"
        answer = question.get("answer")
        if isinstance(answer, list):
            answer = answer[0] if answer else None
        note = (question.get("note") or "").strip() or None
        if answer == GATE_OPTION_CANCEL:
            _write_result(
                artifacts_dir, status="blocked",
                summary="job cancelled by operator",
                blocked_reason="cancelled by operator",
            )
            return StepResult(status="ok")
        if answer == GATE_OPTION_APPROVE and not note:
            (artifacts_dir / "APPROVED").write_text("approved\n", encoding="utf-8")
            _write_result(
                artifacts_dir, status="partial",
                summary="job plan approved; spawning children",
                next_step="spawn",
            )
            return StepResult(status="ok")
        # Revise (explicit option, a note alongside approve, or a free-text
        # note alone — the note always wins, same as the triage loop).
        if note:
            existing = _read_text_capped(
                artifacts_dir / "DESIGN_NOTES.md", DESIGN_NOTES_MAX_CHARS
            )
            block = f"## Operator note\n\n{note}\n"
            combined = (existing.rstrip() + "\n\n" + block) if existing and existing.strip() else block
            (artifacts_dir / "DESIGN_NOTES.md").write_text(combined, encoding="utf-8")
        try:
            (artifacts_dir / "tasks.json").unlink(missing_ok=True)
        except OSError:
            pass
        _write_result(
            artifacts_dir, status="partial",
            summary="job plan needs revision; see DESIGN_NOTES.md",
            next_step="design",
        )
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


def _topo_order(tasks: list[dict]) -> list[dict]:
    """Order validated task dicts so dependencies come first (stable)."""
    by_key = {t["key"]: t for t in tasks}
    ordered: list[dict] = []
    done: set[str] = set()

    def visit(key: str) -> None:
        if key in done:
            return
        done.add(key)
        for dep in by_key[key].get("depends_on") or []:
            visit(dep)
        ordered.append(by_key[key])

    for task in tasks:
        visit(task["key"])
    return ordered


class SpawnChildren:
    """Create child beads from tasks.json, idempotent across crashes."""

    name = "spawn_children"

    def __init__(self, queue_factory: QueueFactory | None = None) -> None:
        self._queue_factory = queue_factory or _default_queue

    async def run(self, ctx: StepContext) -> StepResult:
        artifacts_dir = ctx.task_dir / "artifacts"
        _rotate_result(artifacts_dir)
        doc, load_error = _load_tasks_doc(ctx.task_dir)
        if load_error is not None:
            return self._invalid(ctx, [load_error])
        max_children = getattr(ctx.config, "job_max_children", 30)
        errors = validate_tasks(doc, max_children=max_children)
        if errors:
            return self._invalid(ctx, errors)
        tasks = doc["tasks"]
        ordered = _topo_order(
            [
                {
                    "key": str(t.get("key")).strip(),
                    "title": str(t.get("title")).strip(),
                    "body": str(t.get("body") or ""),
                    "cwd": t.get("cwd"),
                    "coder": t.get("coder"),
                    "model": t.get("model"),
                    "priority": t.get("priority"),
                    "depends_on": list(t.get("depends_on") or []),
                }
                for t in tasks
            ]
        )
        children_file = artifacts_dir / "children.json"
        try:
            existing = json.loads(children_file.read_text(encoding="utf-8"))
            created: dict[str, str] = dict(existing) if isinstance(existing, dict) else {}
        except (OSError, ValueError):
            created = {}

        def _save() -> None:
            tmp = children_file.with_name(children_file.name + ".tmp")
            tmp.write_text(json.dumps(created, indent=2), encoding="utf-8")
            tmp.replace(children_file)

        queue = self._queue_factory(ctx.fleet_home)
        default_coder = getattr(ctx.config, "job_child_coder", None) or None
        default_model = getattr(ctx.config, "job_child_model", None) or None
        design_path = str(artifacts_dir / "DESIGN.md")
        try:
            for task in ordered:
                if task["key"] in created:
                    continue
                try:
                    deps = [created[d] for d in task["depends_on"]]
                except KeyError as exc:
                    return StepResult(
                        status="fail",
                        reason=f"task {task['key']!r} depends on uncreated {exc}",
                    )
                body = task["body"] + (
                    f"\n\nPart of job {ctx.task.id}; DESIGN.md at {design_path}"
                )
                child = queue.create_child(
                    ctx.task.id,
                    {
                        "title": task["title"],
                        "body": body,
                        "cwd": task["cwd"] or ctx.task.cwd,
                        "depends_on": deps,
                        "coder": task["coder"] or default_coder,
                        "model": task["model"] or default_model,
                        "priority": task["priority"],
                    },
                )
                created[task["key"]] = child.id
                _save()
            queue.comment(
                ctx.task.id,
                f"[fleet] job spawned {len(created)} children: {', '.join(created.values())}",
            )
        except Exception as exc:  # noqa: BLE001 - step contract
            return StepResult(status="fail", reason=f"cannot spawn children: {exc}")
        try:
            (artifacts_dir / "DESIGN_ERRORS.md").unlink(missing_ok=True)
        except OSError:
            pass
        _write_result(
            artifacts_dir, status="partial",
            summary=f"spawned {len(created)} children",
            next_step="observe",
        )
        return StepResult(status="ok")

    def _invalid(self, ctx: StepContext, errors: list[str]) -> StepResult:
        artifacts_dir = ctx.task_dir / "artifacts"
        (artifacts_dir / "DESIGN_ERRORS.md").write_text(
            "# tasks.json validation errors\n\n" + "\n".join(f"- {e}" for e in errors) + "\n",
            encoding="utf-8",
        )
        _write_result(
            artifacts_dir, status="partial",
            summary="tasks.json invalid; see DESIGN_ERRORS.md",
            next_step="design",
        )
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


class BlockJob:
    """Terminal worker arm: the phase failed too often, block for a human."""

    name = "block_job"

    def __init__(self, reason: str = "job design failed; see attempts") -> None:
        self._reason = reason

    async def run(self, ctx: StepContext) -> StepResult:
        _write_result(
            ctx.task_dir / "artifacts", status="blocked",
            summary=self._reason, blocked_reason=self._reason,
        )
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


def _snapshot_for(
    ctx: StepContext, queue_factory: QueueFactory | None = None
) -> JobSnapshot:
    """Read the task directory + children into a pure phase snapshot (I/O here)."""
    artifacts_dir = ctx.task_dir / "artifacts"
    has_research = (artifacts_dir / "RESEARCH.md").exists()
    has_tasks = (artifacts_dir / "tasks.json").exists()
    approved = (artifacts_dir / "APPROVED").exists()
    gate_enabled = bool(getattr(ctx.config, "job_gate", True)) and (
        (ctx.task.job_gate or "") != "off"
    )
    try:
        factory = queue_factory or _default_queue
        children = factory(ctx.fleet_home).list_children(ctx.task.id)
        has_children = len(list(children)) > 0
    except Exception:  # noqa: BLE001 - fall back to the spawn journal
        try:
            doc = json.loads((artifacts_dir / "children.json").read_text(encoding="utf-8"))
            has_children = bool(doc)
        except (OSError, ValueError):
            has_children = False
    return JobSnapshot(
        has_research=has_research,
        has_tasks=has_tasks,
        gate_enabled=gate_enabled,
        approved=approved,
        has_children=has_children,
    )


def plan_job(
    ctx: StepContext, queue_factory: QueueFactory | None = None
) -> Worker:
    """Pick the job worker for this attempt: research/design/gate/spawn/observe.

    Reads files and the child list (I/O), then applies the pure
    ``core/job_phase.phase`` table. Research/design attempts that already
    failed ``job_max_phase_attempts`` times become a ``job.blocked`` worker
    instead. Fresh step instances are built on every call (LlmSession holds
    per-attempt subprocess state).
    """
    snapshot = _snapshot_for(ctx, queue_factory)
    current_phase = phase(snapshot)
    if current_phase in ("research", "design"):
        history = [
            a for a in state_attempts.load_attempts(ctx.task_dir)
            if isinstance(a, dict) and a.get("n", 0) < ctx.attempt_n
        ]
        max_attempts = getattr(ctx.config, "job_max_phase_attempts", 2)
        if phase_failures(history, current_phase) >= max_attempts:
            return Worker("job.blocked", (BlockJob(),))
    if current_phase == "research":
        return Worker("job.research", (JobPrepare("research"), LlmSession()))
    if current_phase == "design":
        return Worker("job.design", (JobPrepare("design"), LlmSession()))
    if current_phase == "gate":
        return Worker("job.gate", (AskApproval(),))
    if current_phase == "spawn":
        return Worker("job.spawn", (SpawnChildren(),))
    return Worker(
        "job.observe",
        (WaitChildren(), CollectChildren(), LlmSession(), SpawnFollowups()),
    )
