"""The `job` family: research, design, gate, spawn, then observe.

A bead of type `epic` with metadata ``fleet_worker=job`` (``fleet bd
create --worker job``) decomposes itself instead of being decomposed by a
human: ``plan_job`` reads the task directory into a ``core/job_snapshot``
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

import contextlib
import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fleet.beads.client import BdError
from fleet.beads.queue import Queue
from fleet.core.errors import Json, PlanError, WorkflowSourceUnavailable
from fleet.core.job_phase import phase_failures, phase_of
from fleet.core.job_plan import validate_tasks
from fleet.core.job_snapshot import JobSnapshot
from fleet.core.launch_policy import LaunchPlan
from fleet.core.plan_input import PlanInput
from fleet.core.result import ResultStatus
from fleet.core.task import TaskOutcome, TaskOutcomeRecord
from fleet.state import attempts as state_attempts
from fleet.state.paths import RESULT_JSON
from fleet.state.spawn_journal import spawn_complete

from .base import (
    QuestionLike,
    QuestionStoreLike,
    StepContext,
    StepResult,
    StepStatus,
    Worker,
    merge_run_json,
)
from .llm_session import LlmSession
from .observe import CollectChildren, SpawnFollowups, WaitChildren
from .task_family import ensure_state

# artifacts/RESEARCH.md cap the research prompt enforces (also truncates reads).
RESEARCH_MAX_BYTES = 12 * 1024
# artifacts/candidates.json cap packed into the research_design launch pack.
CANDIDATES_MAX_BYTES = 64 * 1024
# Design pack caps: operator notes and validation errors are bounded inputs.
DESIGN_NOTES_MAX_CHARS = 4 * 1024
DESIGN_ERRORS_MAX_CHARS = 4 * 1024
# ask_human context disambiguating the gate question from triage questions.
JOB_GATE_CONTEXT = "job_gate"
# Research gate prompt: first slice of RESEARCH.md shown instead of task titles.
RESEARCH_GATE_MAX_CHARS = 2500
_DESIGN_MODES = ("design", "research_design")

GATE_OPTION_APPROVE = "approve"
GATE_OPTION_REVISE = "revise (write note)"
GATE_OPTION_CANCEL = "cancel job"
GATE_OPTIONS = [GATE_OPTION_APPROVE, GATE_OPTION_REVISE, GATE_OPTION_CANCEL]


def _ensure_artifact_stubs(task_dir: Path, task_id: str) -> None:
    """Seed the STATE.md stub and outputs/ if missing (see workers/task.py)."""
    ensure_state(task_dir, task_id)


def _write_result(
    task_dir: Path,
    *,
    status: ResultStatus,
    summary: str,
    next_step: str = "",
    blocked_reason: str = "",
) -> None:
    """Write task-level RESULT.json for a Python-decided gate/spawn outcome."""
    task_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": 1,
        "status": status.value,
        "summary": summary,
    }
    if next_step:
        payload["next_step"] = next_step
    if blocked_reason:
        payload["blocked_reason"] = blocked_reason
    (task_dir / RESULT_JSON).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_text_capped(path: Path, cap: int) -> str | None:
    try:
        return path.read_text(encoding="utf-8")[:cap]
    except OSError:
        return None


def _load_tasks_doc(task_dir: Path) -> tuple[Json, str | None]:
    """Return (parsed tasks.json, error); error is None on success."""
    try:
        text = (task_dir / "artifacts" / "tasks.json").read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read tasks.json: {exc}"
    try:
        return json.loads(text), None
    except ValueError as exc:
        return None, f"tasks.json is not valid JSON: {exc}"


def _task_titles(doc: Json) -> list[str]:
    tasks = doc.get("tasks") if isinstance(doc, dict) else None
    if not isinstance(tasks, list):
        return []
    return [str(t.get("title") or t.get("key") or "?") for t in tasks if isinstance(t, dict)]


class JobPrepare:
    """Seed stubs, rotate stale RESULT.json, set the research/design launch pack."""

    name = "job_prepare"

    def __init__(self, mode: str) -> None:
        assert mode in ("research", "design", "research_discover", "research_design")
        self._mode = mode

    async def run(self, ctx: StepContext) -> StepResult:
        _ensure_artifact_stubs(ctx.task_dir, ctx.task.id)
        artifacts_dir = ctx.task_dir / "artifacts"
        if self._mode in _DESIGN_MODES:
            parts = []
            research = _read_text_capped(artifacts_dir / "RESEARCH.md", RESEARCH_MAX_BYTES)
            if research:
                parts.append(f"# RESEARCH.md\n\n{research}")
            if self._mode == "research_design":
                candidates = _read_text_capped(
                    artifacts_dir / "candidates.json", CANDIDATES_MAX_BYTES
                )
                if candidates:
                    parts.append(f"# candidates.json\n\n{candidates}")
            notes = _read_text_capped(artifacts_dir / "DESIGN_NOTES.md", DESIGN_NOTES_MAX_CHARS)
            if notes:
                parts.append(f"# Operator revision notes\n\n{notes}")
            errors = _read_text_capped(artifacts_dir / "DESIGN_ERRORS.md", DESIGN_ERRORS_MAX_CHARS)
            if errors:
                parts.append(f"# Previous validation errors (fix these)\n\n{errors}")
            pack = "\n\n---\n\n".join(parts)
        else:
            pack = ""
        plan = LaunchPlan(
            mode=self._mode,  # type: ignore[arg-type]  # _mode is a launch-mode str; bead 8 declares phase fields
            pack=pack,
            pack_bytes=len(pack.encode("utf-8")),
            needs_compaction=False,
        )
        ctx.launch_plan = plan
        ctx.plan = plan
        merge_run_json(
            ctx,
            launch={"mode": self._mode, "pack_bytes": plan.pack_bytes, "kind": "work"},
        )
        assert ctx.coder is not None
        hook = getattr(ctx.coder, "write_runtime_config", None)
        if hook is not None:
            hook(ctx.workdir, ctx.task)
        return StepResult(status=StepStatus.OK)


def _waiting(reason: str) -> StepResult:
    """An outcome step result that re-releases the bead to wait on a human."""
    return StepResult(
        status=StepStatus.OUTCOME,
        outcome=TaskOutcomeRecord(outcome=TaskOutcome.WAITING, reason=reason),
    )


class AskApproval:
    """Human gate between design and spawn (non-blocking ask_human question)."""

    name = "ask_approval"

    def __init__(self, store: QuestionStoreLike | None = None, *, research: bool = False) -> None:
        self._store = store
        self._research = research

    def _store_for(self, ctx: StepContext) -> QuestionStoreLike | None:
        """Explicit store first, else the store orchestrator/spawn.py injected."""
        if self._store is not None:
            return self._store
        return ctx.question_store

    def _invalid_plan(self, ctx: StepContext, errors: list[str]) -> StepResult:
        """Send an invalid plan back to design without asking the operator."""
        artifacts_dir = ctx.task_dir / "artifacts"
        (artifacts_dir / "DESIGN_ERRORS.md").write_text(
            "# tasks.json validation errors\n\n" + "\n".join(f"- {e}" for e in errors) + "\n",
            encoding="utf-8",
        )
        _write_result(
            ctx.task_dir,
            status=ResultStatus.PARTIAL,
            summary="tasks.json invalid; see DESIGN_ERRORS.md",
            next_step="design",
        )
        return StepResult(status=StepStatus.OK)

    async def run(self, ctx: StepContext) -> StepResult:
        doc, early = self._load_validated(ctx)
        if early is not None:
            return early
        assert doc is not None
        return self._gate(ctx, doc)

    def _load_validated(self, ctx: StepContext) -> tuple[Json | None, StepResult | None]:
        """Load tasks.json and validate it; invalid plans go back to design."""
        doc, load_error = _load_tasks_doc(ctx.task_dir)
        if load_error is not None:
            return None, self._invalid_plan(ctx, [load_error])
        errors = validate_tasks(doc, max_children=ctx.config.job_max_children)
        if errors:
            return None, self._invalid_plan(ctx, errors)
        return doc, None

    def _gate(self, ctx: StepContext, doc: Json) -> StepResult:
        """Apply an existing gate answer, or ask and wait for a new one."""
        store = self._store_for(ctx)
        if store is None:
            return StepResult(status=StepStatus.FAIL, reason="no question store injected")
        answered = self._store_read(
            store, "answers", lambda: store.fetch_answered_for_task(ctx.task.id, JOB_GATE_CONTEXT)
        )
        if isinstance(answered, StepResult):
            return answered
        if answered:
            return self._apply_answer(ctx, answered[-1])
        pending = self._store_read(
            store, "questions", lambda: store.fetch_pending_for_task(ctx.task.id, JOB_GATE_CONTEXT)
        )
        if isinstance(pending, StepResult):
            return pending
        if pending:
            return _waiting("waiting for job gate approval")
        return self._ask(ctx, store, doc)

    @staticmethod
    def _store_read(store: QuestionStoreLike, label: str, thunk: Callable[[], Any]) -> Any:
        """Run a gate store read; store failures become a fail result."""
        try:
            return thunk()
        except Exception as exc:  # noqa: BLE001 - step contract: return fail, never raise
            return StepResult(status=StepStatus.FAIL, reason=f"cannot read gate {label}: {exc}")

    def _ask(self, ctx: StepContext, store: QuestionStoreLike, doc: Json) -> StepResult:
        """Post the approval question, then wait for the operator."""
        titles = _task_titles(doc)
        if self._research:
            research_md = (
                _read_text_capped(
                    ctx.task_dir / "artifacts" / "RESEARCH.md", RESEARCH_GATE_MAX_CHARS
                )
                or ""
            )
            prompt = f"{research_md}\napprove {len(titles)} tasks?"
        else:
            prompt = f"Job {ctx.task.id}: approve {len(titles)} tasks?\n" + "\n".join(
                f"- {t}" for t in titles
            )
        try:
            store.ask(
                prompt,
                list(GATE_OPTIONS),
                task_id=ctx.task.id,
                context=JOB_GATE_CONTEXT,
                agent_id="job",
            )
        except Exception as exc:  # noqa: BLE001 - step contract
            return StepResult(status=StepStatus.FAIL, reason=f"cannot ask gate question: {exc}")
        return _waiting("waiting for job gate approval")

    def _apply_answer(self, ctx: StepContext, question: QuestionLike) -> StepResult:
        """Apply the operator's gate answer: approve, revise, or cancel."""
        task_dir = ctx.task_dir
        artifacts_dir = task_dir / "artifacts"
        answer = question.get("answer")
        if isinstance(answer, list):
            answer = answer[0] if answer else None
        note = (question.get("note") or "").strip() or None
        if answer == GATE_OPTION_CANCEL:
            _write_result(
                task_dir,
                status=ResultStatus.BLOCKED,
                summary="job cancelled by operator",
                blocked_reason="cancelled by operator",
            )
            return StepResult(status=StepStatus.OK)
        if answer == GATE_OPTION_APPROVE and not note:
            (artifacts_dir / "APPROVED").write_text("approved\n", encoding="utf-8")
            _write_result(
                task_dir,
                status=ResultStatus.PARTIAL,
                summary="job plan approved; spawning children",
                next_step="spawn",
            )
            return StepResult(status=StepStatus.OK)
        return self._apply_revise(task_dir, artifacts_dir, note)

    def _apply_revise(self, task_dir: Path, artifacts_dir: Path, note: str | None) -> StepResult:
        """Send the plan back to design, keeping the operator's note if any.

        Covers the explicit revise option, a note alongside approve, and a
        free-text note alone — the note always wins, same as triage.
        """
        if note:
            existing = _read_text_capped(artifacts_dir / "DESIGN_NOTES.md", DESIGN_NOTES_MAX_CHARS)
            block = f"## Operator note\n\n{note}\n"
            combined = (
                (existing.rstrip() + "\n\n" + block) if existing and existing.strip() else block
            )
            (artifacts_dir / "DESIGN_NOTES.md").write_text(combined, encoding="utf-8")
        with contextlib.suppress(OSError):
            (artifacts_dir / "tasks.json").unlink(missing_ok=True)
        _write_result(
            task_dir,
            status=ResultStatus.PARTIAL,
            summary="job plan needs revision; see DESIGN_NOTES.md",
            next_step="design",
        )
        return StepResult(status=StepStatus.OK)


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


def _normalize_task(raw: dict) -> dict:
    """Keep one validated tasks.json entry's spawn fields with stripped text."""
    return {
        "key": str(raw.get("key")).strip(),
        "title": str(raw.get("title")).strip(),
        "body": str(raw.get("body") or ""),
        "cwd": raw.get("cwd"),
        "coder": raw.get("coder"),
        "model": raw.get("model"),
        "priority": raw.get("priority"),
        "depends_on": list(raw.get("depends_on") or []),
        "workflow": raw.get("workflow"),
        "inputs": dict(raw.get("inputs") or {}),
    }


#: How often one key may be deferred before it counts as a dead source.
#: A host-side block clears in minutes; a source that is still unreachable
#: after this many spawn attempts is written off so the job can finish.
_DEFER_MAX_ATTEMPTS = 5


@dataclass
class _SpawnJournals:
    """The three spawn journals (key -> value) and the files they live in."""

    artifacts_dir: Path
    created: dict[str, str]
    runs: dict[str, dict]
    skipped: dict[str, str]
    deferred: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, artifacts_dir: Path) -> _SpawnJournals:
        return cls(
            artifacts_dir=artifacts_dir,
            created=_load_journal(artifacts_dir / "children.json"),
            runs=_load_runs_journal(artifacts_dir / "children_runs.json"),
            skipped=_load_journal(artifacts_dir / "children_skipped.json"),
            deferred=_load_runs_journal(artifacts_dir / "children_deferred.json"),
        )

    def save_created(self) -> None:
        _write_json_atomic(self.artifacts_dir / "children.json", self.created)

    def save_runs(self) -> None:
        _write_json_atomic(self.artifacts_dir / "children_runs.json", self.runs)

    def skip(self, key: str, reason: str) -> None:
        self.skipped[key] = reason
        _write_json_atomic(self.artifacts_dir / "children_skipped.json", self.skipped)

    def defer(self, key: str, reason: str, previous: dict[str, dict]) -> None:
        """Leave *key* for the next attempt, or skip it once the budget is out.

        A source can be unreachable because the host is blocking us, which
        passes, or because it is genuinely unreadable in a way the host
        reports ambiguously (YouTube hides caption tracks while it blocks,
        so "transcripts are disabled" means either). Counting attempts lets
        the first case recover and still writes the second one off.
        """
        attempts = int(previous.get(key, {}).get("attempts", 0)) + 1
        if attempts >= _DEFER_MAX_ATTEMPTS:
            self.skip(key, f"unreachable on {attempts} attempts; last: {reason}")
            return
        self.deferred[key] = {"reason": reason, "attempts": attempts}

    def save_deferred(self) -> None:
        """Record keys left for the next attempt; a report, not a gate.

        Nothing reads this back — the keys are simply absent from the other
        journals, so `spawn_complete` stays false and the next spawn retries
        them. It exists so an operator can see why an attempt ended with
        work outstanding.
        """
        _write_json_atomic(self.artifacts_dir / "children_deferred.json", self.deferred)


def _load_journal(children_file: Path) -> dict[str, str]:
    """Read the spawn journal (key -> child id); empty when missing/corrupt."""
    try:
        existing = json.loads(children_file.read_text(encoding="utf-8"))
        return dict(existing) if isinstance(existing, dict) else {}
    except (OSError, ValueError):
        return {}


def _load_runs_journal(runs_file: Path) -> dict[str, dict]:
    """Read the workflow-run journal (key -> run entry or starting intent)."""
    try:
        existing = json.loads(runs_file.read_text(encoding="utf-8"))
        return dict(existing) if isinstance(existing, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json_atomic(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* via a tmp file + replace (crash-safe)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def _is_dep_conflict(exc: BdError) -> bool:
    """True when *exc* is bd rejecting a dependency that already exists."""
    return "already exists" in str(exc).lower()


def _run_entry_complete(entry: dict | None) -> bool:
    """True when a children_runs.json entry claims a started run (has run_id)."""
    return entry is not None and bool(entry.get("run_id"))


class SpawnChildren:
    """Create child beads from tasks.json, idempotent across crashes."""

    name = "spawn_children"

    def __init__(self, queue: Queue) -> None:
        self._queue = queue

    async def run(self, ctx: StepContext) -> StepResult:
        ordered, early = self._load_ordered(ctx)
        if early is not None:
            return early
        assert ordered is not None
        artifacts_dir = ctx.task_dir / "artifacts"
        journals = _SpawnJournals.load(artifacts_dir)
        created, skipped = journals.created, journals.skipped
        before = len(created)
        queue = self._queue
        workflow_keys = {task["key"] for task in ordered if task["workflow"]}
        try:
            self._spawn_missing(ctx, queue, ordered, journals)
            labels = [f"run:{v}" if k in workflow_keys else v for k, v in created.items()]
            note = f"[fleet] job spawned {len(created)} children: {', '.join(labels)}"
            if skipped:
                rows = "\n".join(f"- {key}: {reason}" for key, reason in skipped.items())
                note += f"\n\nskipped {len(skipped)} (artifacts/children_skipped.json):\n{rows}"
            if journals.deferred:
                note += (
                    f"\n\ndeferred {len(journals.deferred)} to the next attempt "
                    "(artifacts/children_deferred.json): the source could not be reached "
                    "right now (rate limit, IP block, timeout)"
                )
            queue.comment(ctx.task.id, note)
        except Exception as exc:  # noqa: BLE001 - step contract
            return StepResult(status=StepStatus.FAIL, reason=f"cannot spawn children: {exc}")
        if not created:
            return StepResult(
                status=StepStatus.FAIL,
                reason=f"cannot spawn children: every task was skipped ({len(skipped)})",
            )
        if journals.deferred and len(created) == before:
            # Nothing moved and the rest is unreachable. Spawn stays incomplete,
            # so the epic would be handed straight back and would hammer the
            # same host again; block instead and let a human release it once
            # the source answers.
            reason = (
                f"{len(journals.deferred)} children could not be spawned: their sources "
                "are unreachable right now (rate limit, IP block, timeout). "
                "See artifacts/children_deferred.json; unblock this job to retry them."
            )
            _write_result(
                ctx.task_dir,
                status=ResultStatus.BLOCKED,
                summary=reason,
                blocked_reason=reason,
            )
            return StepResult(status=StepStatus.OK)
        with contextlib.suppress(OSError):
            (artifacts_dir / "DESIGN_ERRORS.md").unlink(missing_ok=True)
        summary = f"spawned {len(created)} children"
        if skipped:
            summary += f", skipped {len(skipped)}"
        if journals.deferred:
            summary += f", deferred {len(journals.deferred)}"
        _write_result(
            ctx.task_dir,
            status=ResultStatus.PARTIAL,
            summary=summary,
            next_step="observe",
        )
        return StepResult(status=StepStatus.OK)

    def _load_ordered(self, ctx: StepContext) -> tuple[list[dict] | None, StepResult | None]:
        """Load tasks.json, validate it, and order entries dependencies-first."""
        doc, load_error = _load_tasks_doc(ctx.task_dir)
        if load_error is not None:
            return None, self._invalid(ctx, [load_error])
        assert doc is not None and isinstance(doc, dict)
        errors = validate_tasks(doc, max_children=ctx.config.job_max_children)
        if errors:
            return None, self._invalid(ctx, errors)
        tasks = doc.get("tasks")
        assert isinstance(tasks, list)
        return (
            _topo_order([_normalize_task(t) for t in tasks if isinstance(t, dict)]),
            None,
        )

    def _spawn_missing(
        self,
        ctx: StepContext,
        queue: Queue,
        ordered: list[dict],
        journals: _SpawnJournals,
    ) -> None:
        """Create every not-yet-spawned child, journaling each id at once.

        A workflow child whose builder fails for good (dead link, no
        transcript, ...) is journaled in ``children_skipped.json`` instead
        of aborting the whole spawn; tasks that depended only on skipped
        keys are skipped too, and other tasks simply drop the skipped
        dependency. A child whose source was merely unreachable is deferred
        instead, and so is anything waiting on it: neither is created, so
        the next attempt picks both up.
        """
        design_path = str(journals.artifacts_dir / "DESIGN.md")
        created, runs, skipped = journals.created, journals.runs, journals.skipped
        self._start_workflow_runs(ctx, ordered, journals)
        deferred = journals.deferred
        for task in ordered:
            if task["key"] in skipped or task["key"] in deferred:
                continue
            if task["workflow"]:
                self._spawn_workflow_child(ctx, queue, task, journals)
                continue
            if task["key"] in created:
                continue
            waits = [key for key in task["depends_on"] if key in deferred]
            if waits:
                # Following a deferred dependency is not the task's own
                # failure, so it spends no retry budget.
                deferred[task["key"]] = {
                    "reason": f"waits for deferred {', '.join(waits)}",
                    "attempts": 0,
                }
                continue
            try:
                deps = []
                for dep_key in task["depends_on"]:
                    if dep_key in skipped:
                        continue
                    run = runs.get(dep_key)
                    if run is not None and run.get("final_task_ids") is not None:
                        deps.extend(run["final_task_ids"])
                    else:
                        deps.append(created[dep_key])
            except KeyError as exc:
                raise PlanError(f"task {task['key']!r} depends on uncreated {exc}") from exc
            if task["depends_on"] and not deps:
                gone = ", ".join(task["depends_on"])
                journals.skip(task["key"], f"every dependency was skipped ({gone})")
                continue
            body = task["body"] + (f"\n\nPart of job {ctx.task.id}; DESIGN.md at {design_path}")
            child = queue.create_child(
                ctx.task.id,
                {
                    "title": task["title"],
                    "body": body,
                    "cwd": task["cwd"] or ctx.task.cwd,
                    "depends_on": deps,
                    "coder": task["coder"] or ctx.config.job_child_coder or None,
                    "model": task["model"] or ctx.config.job_child_model or None,
                    "priority": task["priority"],
                },
            )
            created[task["key"]] = child.id
            journals.save_created()
        journals.save_deferred()

    def _start_workflow_runs(
        self,
        ctx: StepContext,
        ordered: list[dict],
        journals: _SpawnJournals,
    ) -> None:
        """Start every not-yet-started workflow child, several at a time.

        A workflow run expands its builder at start, which fetches the
        source over the network, so starting 150 of them one after another
        takes far longer than one attempt. Workflow children never depend
        on each other, so they start concurrently; each result is journaled
        as it arrives, guarded by a lock because the completions land on
        pool threads sharing one journals object.

        The intent (``{"status": "starting", ...}``) is journaled BEFORE the
        pool starts, so an attempt killed mid-spawn leaves a breadcrumb: the
        next attempt retries those keys, and the runner's inputs dedupe
        reuses the orphaned run instead of starting a second chain.
        """
        runs = journals.runs
        todo = [
            task
            for task in ordered
            if task["workflow"]
            and task["key"] not in journals.skipped
            and not _run_entry_complete(runs.get(task["key"]))
        ]
        if not todo:
            return
        if ctx.workflow_runner is None:
            raise PlanError("workflow children need a workflow runner")
        runner = ctx.workflow_runner
        previous = dict(journals.deferred)
        journals.deferred.clear()
        for task in todo:
            runs[task["key"]] = {
                "status": "starting",
                "workflow": task["workflow"],
                "inputs": dict(task["inputs"]),
            }
        journals.save_runs()
        journal_lock = threading.Lock()
        width = max(1, min(ctx.config.job_spawn_parallel, len(todo)))
        parent_task_id = ctx.task.id
        with ThreadPoolExecutor(max_workers=width) as pool:
            futures = {
                pool.submit(
                    runner.start,
                    task["workflow"],
                    task["inputs"],
                    parent_task_id=parent_task_id,
                ): task["key"]
                for task in todo
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    handle = future.result()
                except WorkflowSourceUnavailable as exc:
                    # Rate limit, IP block, timeout: the source is fine, this
                    # moment is not. Journaling a skip here would drop it from
                    # the run for good, so leave the key for the next attempt.
                    with journal_lock:
                        journals.defer(key, str(exc), previous)
                        journals.runs.pop(key, None)
                        journals.save_runs()
                    continue
                except ValueError as exc:  # WorkflowInvalid, unknown workflow, bad input
                    with journal_lock:
                        journals.skip(key, str(exc))
                        journals.runs.pop(key, None)
                        journals.save_runs()
                    continue
                with journal_lock:
                    journals.runs[key] = {
                        "run_id": handle.run_id,
                        "task_ids": list(handle.task_ids),
                        "final_task_ids": list(handle.final_task_ids),
                    }
                    journals.created[key] = handle.run_id
                    journals.save_runs()
                    journals.save_created()
        journals.save_deferred()

    def _spawn_workflow_child(
        self,
        ctx: StepContext,
        queue: Queue,
        task: dict,
        journals: _SpawnJournals,
    ) -> None:
        """Wire the epic to one already-started workflow run.

        Every run is started by ``_start_workflow_runs``; a key missing
        from the journal (or holding only a ``starting`` intent left by a
        killed attempt) was deferred there and is left for the next attempt.
        ``add_dependency`` re-runs on every attempt (tolerating bd's
        already-exists error) so a crash between journaling and full wiring
        still converges.
        """
        key = task["key"]
        run = journals.runs.get(key)
        if not _run_entry_complete(run):
            return
        assert run is not None
        # The steps inside a run are chained, so waiting for its last stage
        # is waiting for the whole run; wiring every step would cost one bd
        # call per step (thousands for a large research job).
        wait_for = run["final_task_ids"] or run["task_ids"]
        for task_id in wait_for:
            try:
                queue.add_dependency(ctx.task.id, task_id)
            except BdError as exc:
                if not _is_dep_conflict(exc):
                    raise

    def _invalid(self, ctx: StepContext, errors: list[str]) -> StepResult:
        artifacts_dir = ctx.task_dir / "artifacts"
        (artifacts_dir / "DESIGN_ERRORS.md").write_text(
            "# tasks.json validation errors\n\n" + "\n".join(f"- {e}" for e in errors) + "\n",
            encoding="utf-8",
        )
        _write_result(
            ctx.task_dir,
            status=ResultStatus.PARTIAL,
            summary="tasks.json invalid; see DESIGN_ERRORS.md",
            next_step="design",
        )
        return StepResult(status=StepStatus.OK)


class BlockJob:
    """Terminal worker arm: the phase failed too often, block for a human."""

    name = "block_job"

    def __init__(self, reason: str = "job design failed; see attempts") -> None:
        self._reason = reason

    async def run(self, ctx: StepContext) -> StepResult:
        _write_result(
            ctx.task_dir,
            status=ResultStatus.BLOCKED,
            summary=self._reason,
            blocked_reason=self._reason,
        )
        return StepResult(status=StepStatus.OK)


def snapshot_for(plan: PlanInput, queue: Queue) -> JobSnapshot:
    """Read the task directory + children into a pure phase snapshot (I/O here)."""
    artifacts_dir = plan.task_dir / "artifacts"
    has_research = (artifacts_dir / "RESEARCH.md").exists()
    has_tasks = (artifacts_dir / "tasks.json").exists()
    approved = (artifacts_dir / "APPROVED").exists()
    gate_enabled = bool(plan.config.job_gate) and ((plan.task.job_gate or "") != "off")
    try:
        children = queue.list_children(plan.task.id)
        has_children = len(list(children)) > 0
    except Exception:  # noqa: BLE001 - fall back to the spawn journal
        has_children = bool(_load_journal(artifacts_dir / "children.json"))
    # Spawn journals each child as it is created, so a crash mid-spawn leaves
    # some children behind. Stay in the spawn phase until every tasks.json
    # key has been journaled; SpawnChildren skips the ones already created.
    if has_children and not spawn_complete(plan.task_dir):
        has_children = False
    return JobSnapshot(
        has_research=has_research,
        has_tasks=has_tasks,
        gate_enabled=gate_enabled,
        approved=approved,
        has_children=has_children,
    )


def plan_job(
    plan: PlanInput,
    queue: Queue,
    store: QuestionStoreLike | None = None,
) -> Worker:
    """Pick the job worker for this attempt: research/design/gate/spawn/observe.

    Reads files and the child list (I/O), then applies the pure
    ``core/job_phase.phase_of`` table. Research/design attempts that already
    failed ``job_max_phase_attempts`` times become a ``job.blocked`` worker
    instead. Fresh step instances are built on every call (LlmSession holds
    per-attempt subprocess state). The queue and the gate store come from
    the worker factory (``workers/__init__.py``); this module never builds
    either.
    """
    snapshot = snapshot_for(plan, queue)
    current_phase = phase_of(snapshot)
    if current_phase in ("research", "design"):
        history = [
            a
            for a in state_attempts.load_attempts(plan.task_dir)
            if isinstance(a, dict) and a.get("n", 0) < plan.attempt_n
        ]
        max_attempts = plan.config.job_max_phase_attempts
        if phase_failures(history, current_phase) >= max_attempts:
            return Worker("job.blocked", (BlockJob(),))
    if current_phase == "research":
        return Worker("job.research", (JobPrepare("research"), LlmSession()))
    if current_phase == "design":
        return Worker("job.design", (JobPrepare("design"), LlmSession()))
    if current_phase == "gate":
        return Worker("job.gate", (AskApproval(store),))
    if current_phase == "spawn":
        return Worker("job.spawn", (SpawnChildren(queue),))
    return Worker(
        "job.observe",
        (WaitChildren(queue), CollectChildren(queue), LlmSession(), SpawnFollowups(queue)),
    )
