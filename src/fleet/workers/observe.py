"""The `observer` family: validate a finished epic, open follow-ups.

``plan_observer`` is the family's `plan(ctx)` entry point (see
``workers/__init__.py``): an epic bead whose children are all terminal
runs ``WaitChildren`` (re-release when a child still runs) →
``CollectChildren`` (bounded ``CHILDREN.md`` digest) → ``LlmSession`` in
``validate`` mode (checks the repo against the epic goal, writes
RESULT.json) → ``SpawnFollowups`` (opens follow-up children on partial).

Only ``LlmSession`` talks to a model and holds a concurrency slot; the
other three steps are pure Python and exit in seconds.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fleet.beads.queue import BeadsQueue
from fleet.core.job_plan import validate_followups
from fleet.core.job_ready import BeadSummary, children_terminal
from fleet.core.launch import LaunchPlan
from fleet.core.result import parse_result
from fleet.core.task import TaskOutcome, TaskOutcomeRecord
from fleet.state import attempts as state_attempts
from fleet.state.paths import task_dir as task_dir_path

from .base import StepContext, StepResult, Worker
from .llm_session import LlmSession

# artifacts/CHILDREN.md is bounded by construction: each child section is
# capped, and oldest sections are dropped first past the total cap.
CHILDREN_MD_MAX_BYTES = 8 * 1024
CHILD_SECTION_MAX_CHARS = 600

QueueFactory = Callable[[Path], Any]


def _default_queue(home: Path) -> BeadsQueue:
    return BeadsQueue(home)


def _as_summaries(children: list) -> list[BeadSummary]:
    """Normalize queue/dict child rows to BeadSummary (test fakes vary)."""
    out: list[BeadSummary] = []
    for c in children:
        if isinstance(c, dict):
            out.append(
                BeadSummary(id=str(c.get("id")), status=str(c.get("status") or ""))
            )
        else:
            out.append(BeadSummary(id=str(c.id), status=str(c.status)))
    return out


def _rotate_result(artifacts_dir: Path) -> None:
    """Move a previous attempt's RESULT.json aside before this attempt runs.

    Same guarantee as the task family's PrepareArtifacts: a stale file can
    never be mistaken for this attempt's outcome (in particular, reap must
    not snapshot or fold last round's verdict into a WAITING attempt).
    """
    result_file = artifacts_dir / "RESULT.json"
    if result_file.exists():
        result_file.replace(artifacts_dir / "RESULT.prev.json")


class WaitChildren:
    """Re-release the epic while any child still runs (outcome WAITING)."""

    name = "wait_children"

    def __init__(self, queue_factory: QueueFactory | None = None) -> None:
        self._queue_factory = queue_factory or _default_queue

    async def run(self, ctx: StepContext) -> StepResult:
        _rotate_result(ctx.task_dir / "artifacts")
        try:
            children = _as_summaries(
                self._queue_factory(ctx.fleet_home).list_children(ctx.task.id)
            )
        except Exception as exc:  # noqa: BLE001 - step contract: return fail, never raise
            return StepResult(status="fail", reason=f"cannot list children: {exc}")
        ctx.scratch["children"] = [
            {"id": c.id, "status": c.status} for c in children
        ]
        if children_terminal(children):
            return StepResult(status="ok")
        running = [c for c in children if c.status not in ("closed", "blocked")]
        return StepResult(
            status="outcome",
            outcome=TaskOutcomeRecord(
                outcome=TaskOutcome.WAITING,
                reason=f"{len(running)} of {len(children)} children still running",
            ),
        )

    async def cancel(self, reason: str) -> None:
        return None


def _summary_facts(text: str) -> tuple[list[str], int]:
    """Pull (commit shas, files-touched count) out of an attempt SUMMARY.md."""
    commits: list[str] = []
    files = 0
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if not line.startswith("- "):
            continue
        if section == "commits":
            words = line[2:].split()
            if words and words[0] != "(none)":
                commits.append(words[0])
        elif section == "files touched":
            files += 1
    return commits[:5], files


def _child_digest(child_id: str, fleet_home: Path) -> dict:
    """Collect one child's RESULT status/summary, commits, files, block reason."""
    task_dir = task_dir_path(fleet_home, child_id)
    status, summary = "unknown", ""
    try:
        text = (task_dir / "artifacts" / "RESULT.json").read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text:
        result = parse_result(text)
        if result is not None:
            status, summary = result.status, result.summary
    commits: list[str] = []
    files = 0
    outcome = ""
    latest = state_attempts.latest_attempt_dir(task_dir)
    if latest is not None:
        try:
            facts_text = (latest / "SUMMARY.md").read_text(encoding="utf-8")
        except OSError:
            facts_text = ""
        if facts_text:
            commits, files = _summary_facts(facts_text)
    history = state_attempts.load_attempts(task_dir)
    if history:
        last = history[-1]
        outcome = str(last.get("outcome") or "")
    blocked_reason = ""
    try:
        meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if isinstance(meta, dict) and meta.get("blocked_reason"):
        blocked_reason = str(meta["blocked_reason"])
    return {
        "status": status,
        "summary": summary,
        "commits": commits,
        "files": files,
        "outcome": outcome,
        "blocked_reason": blocked_reason,
    }


def _render_child_section(child_id: str, bead_status: str, digest: dict) -> str:
    """One ≤600-char CHILDREN.md section for a child bead."""
    lines = [
        f"## {child_id} — bead {bead_status}, RESULT {digest['status']}",
        (digest["summary"] or "(no summary)")[:200],
    ]
    if digest["commits"]:
        lines.append("commits: " + ", ".join(digest["commits"]))
    if digest["files"]:
        lines.append(f"files touched: {digest['files']}")
    if digest["outcome"]:
        lines.append(f"last attempt outcome: {digest['outcome']}")
    if digest["blocked_reason"]:
        lines.append(f"blocked_reason: {digest['blocked_reason'][:200]}")
    return "\n".join(lines)[:CHILD_SECTION_MAX_CHARS]


class CollectChildren:
    """Digest every child into artifacts/CHILDREN.md (≤ 8 KB) for the validator."""

    name = "collect_children"

    def __init__(self, queue_factory: QueueFactory | None = None) -> None:
        self._queue_factory = queue_factory or _default_queue

    async def run(self, ctx: StepContext) -> StepResult:
        raw = ctx.scratch.get("children")
        if raw is None:
            try:
                raw = [
                    {"id": c.id, "status": c.status}
                    for c in _as_summaries(
                        self._queue_factory(ctx.fleet_home).list_children(ctx.task.id)
                    )
                ]
            except Exception as exc:  # noqa: BLE001 - step contract
                return StepResult(status="fail", reason=f"cannot list children: {exc}")
        sections = [
            _render_child_section(
                str(c.get("id")), str(c.get("status") or ""), _child_digest(str(c.get("id")), ctx.fleet_home)
            )
            for c in raw
            if isinstance(c, dict) and c.get("id")
        ]
        # Bounded by construction: oldest sections drop first past the cap.
        while len("\n\n".join(sections).encode("utf-8")) > CHILDREN_MD_MAX_BYTES and sections:
            sections.pop(0)
        body = "# Children digest\n\n" + "\n\n".join(sections) if sections else "# Children digest\n\n(none)"
        artifacts_dir = ctx.task_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "CHILDREN.md").write_text(body, encoding="utf-8")
        blocked = sum(1 for c in raw if isinstance(c, dict) and c.get("status") == "blocked")
        ctx.scratch["child_ids"] = [str(c["id"]) for c in raw if isinstance(c, dict) and c.get("id")]
        ctx.scratch["blocked_children"] = blocked
        pack_bytes = len(body.encode("utf-8"))
        ctx.scratch["launch_plan"] = LaunchPlan(
            mode="validate", pack=body, pack_bytes=pack_bytes, needs_compaction=False
        )
        attempt_dir = ctx.attempt_dir or ctx.task_dir
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "launch.json").write_text(
            json.dumps({"mode": "validate", "pack_bytes": pack_bytes, "kind": "work"}),
            encoding="utf-8",
        )
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


class SpawnFollowups:
    """Open validated follow-up children when RESULT.json declares them."""

    name = "spawn_followups"

    def __init__(self, queue_factory: QueueFactory | None = None) -> None:
        self._queue_factory = queue_factory or _default_queue

    async def run(self, ctx: StepContext) -> StepResult:
        try:
            text = (ctx.task_dir / "artifacts" / "RESULT.json").read_text(encoding="utf-8")
        except OSError:
            return StepResult(status="ok")
        result = parse_result(text)
        if result is None or result.status != "partial" or not result.followups:
            return StepResult(status="ok")
        max_followups = getattr(ctx.config, "observer_max_followups", 10)
        try:
            specs = validate_followups(result.followups, max_followups=max_followups)
        except ValueError as exc:
            try:
                self._queue_factory(ctx.fleet_home).comment(
                    ctx.task.id, f"[fleet] ignoring invalid follow-ups: {exc}"
                )
            except Exception:  # noqa: BLE001 - commenting is best effort
                pass
            return StepResult(status="ok")
        queue = self._queue_factory(ctx.fleet_home)
        created: dict[str, str] = {}
        try:
            for spec in specs:
                deps = [created[d] for d in spec["depends_on"]]
                body = spec["body"] or f"Follow-up for {ctx.task.id}: {spec['title']}"
                child = queue.create_child(
                    ctx.task.id,
                    {
                        "title": spec["title"],
                        "body": body,
                        "cwd": spec["cwd"] or ctx.task.cwd,
                        "depends_on": deps,
                    },
                )
                created[spec["title"]] = child.id
            queue.comment(
                ctx.task.id,
                f"[fleet] opened {len(created)} follow-ups: {', '.join(created.values())}",
            )
        except Exception as exc:  # noqa: BLE001 - step contract
            return StepResult(status="fail", reason=f"cannot spawn follow-ups: {exc}")
        return StepResult(status="ok")

    async def cancel(self, reason: str) -> None:
        return None


# Canonical observer pipeline (see ADR 0003). `plan_observer` below builds
# fresh step instances per attempt instead of reusing these: LlmSession
# holds per-attempt subprocess state on `self`, and attempts run
# concurrently across tasks.
Observer = Worker(
    "observer", (WaitChildren(), CollectChildren(), LlmSession(), SpawnFollowups())
)


def plan_observer(ctx: StepContext) -> Worker:
    """Pick the observer worker: always the full validate pipeline.

    Branching lives in the steps, not here: WaitChildren re-releases while
    children run, and SpawnFollowups is a no-op unless RESULT.json declares
    follow-ups — so one static list covers every epic attempt.
    """
    _ = ctx
    return Worker(
        Observer.name, (WaitChildren(), CollectChildren(), LlmSession(), SpawnFollowups())
    )
