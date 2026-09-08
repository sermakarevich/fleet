"""Reap service: collect finished workers, apply the outcome, notify the rest.

Reap is event-driven, not periodic: it waits for the first in-flight
future to finish, removes its RunningWorker from the shared state, folds
the outcome through the retry policy, and emits `on_worker_finished` so
other services (StallWatch) can drop their per-task scratch data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.core import retry_policy
from fleet.core.job_plan import observer_rounds
from fleet.core.result import Result, parse_result
from fleet.core.retry_policy import (
    CONTEXT_MAX_ROUNDS,
    NOCLOSE_MAX_ROUNDS,
    PARTIAL_MAX_ROUNDS,
    Action,
    Decision,
)
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.state import attempts
from fleet.state.paths import RESULT_JSON, STATE_MD
from fleet.state.validation_marker import set_needs_validation

from . import worktree
from .claim import read_isolation_info
from .service import Service, ServiceOrder, emit
from .status_log import fleet_log_context

if TYPE_CHECKING:
    from .state import RunningWorker, SupervisorState

_STALE_COUNTER_FILES = (".failures", ".noclose", ".stalls")


def _drop_stale_counter_files(task_dir: Path) -> None:
    """Remove pre-retry-policy counter files; rounds now come from attempts.jsonl."""
    for name in _STALE_COUNTER_FILES:
        try:
            (task_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


def pop_finished(st: SupervisorState, fut: asyncio.Task) -> RunningWorker | None:
    """Remove and return the RunningWorker that owns `fut`, or None when unknown."""
    task_id = next((tid for tid, rw in st.running.items() if rw.future is fut), None)
    if task_id is None:
        return None
    return st.running.pop(task_id)


def outcome_of(fut: asyncio.Task) -> TaskOutcomeRecord:
    """Unwrap a finished future into its outcome record, or FAILURE when it raised."""
    try:
        return fut.result()
    except Exception as exc:
        return TaskOutcomeRecord(
            outcome=TaskOutcome.FAILURE,
            reason=f"unexpected exception: {exc}",
        )


def bead_status(st: SupervisorState, task_id: str) -> str | None:
    """Current bead status, or None when the queue lookup fails."""
    try:
        return st.queue.get(task_id).status
    except Exception:
        return None


def read_declared_result(task_dir: Path) -> Result | None:
    """Parse the task-level RESULT.json, the worker's declared outcome, if present."""
    try:
        text = (task_dir / RESULT_JSON).read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_result(text)


def fold_declared_result(record: TaskOutcomeRecord, result: Result) -> TaskOutcomeRecord:
    """Fold a declared RESULT.json into an rc=0 outcome record."""
    if result.status == "done":
        return TaskOutcomeRecord(
            outcome=TaskOutcome.SUCCESS,
            exit_code=record.exit_code,
            reason=result.summary,
            close_reason=result.summary or "completed",
        )
    if result.status == "partial":
        return TaskOutcomeRecord(
            outcome=TaskOutcome.PARTIAL,
            exit_code=record.exit_code,
            reason=result.next_step or result.summary,
        )
    return TaskOutcomeRecord(
        outcome=TaskOutcome.BLOCKED_BY_AGENT,
        exit_code=record.exit_code,
        reason=result.blocked_reason or result.summary,
    )


def maybe_handle_isolated_success(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    status: str | None,
    result: Result | None = None,
) -> Decision | None:
    """Decide an isolated (worktree) SUCCESS exit, or None when it is not one."""
    if record.outcome != TaskOutcome.SUCCESS or status != "in_progress":
        return None
    info = read_isolation_info(task_dir)
    if info is None:
        return None
    if result is None or result.status != "done":
        return None

    wt_path = Path(info["worktree_path"])
    base_ref = info.get("base_ref") or "main"
    if worktree.is_committed_clean(wt_path, base_ref=base_ref):
        set_needs_validation(task_dir)
        st.log.info("task.needs_validation", task_id=task.id)
        return Decision(Action.NOOP, reason="needs validation")

    if not worktree.has_uncommitted_changes(wt_path):
        st.log.info("task.isolated_no_repo_changes", task_id=task.id)
        discard_isolation(st, task, task_dir, info)
        return None

    history = attempts.load_attempts(task_dir)
    rounds = retry_policy._trailing_streak(history, "noclose") + 1
    detail = f"uncommitted changes left in {wt_path}"
    if rounds >= NOCLOSE_MAX_ROUNDS:
        return Decision(
            Action.BLOCK,
            reason=(
                f"isolated task exited without a clean commit ({detail}) "
                f"({rounds}/{NOCLOSE_MAX_ROUNDS}); needs human review"
            ),
        )
    return Decision(
        Action.RELEASE,
        reason=(
            f"isolated task exited without a clean commit ({detail}) "
            f"(#{rounds}/{NOCLOSE_MAX_ROUNDS}); commit or revert them"
        ),
        wait_sec=0,
    )


def discard_isolation(st: SupervisorState, task: Task, task_dir: Path, info: dict) -> None:
    """Remove a worktree that carries no work and forget the isolation info."""
    repo_root = info.get("repo_root") or ""
    wt_path = Path(info["worktree_path"])
    if repo_root:
        worktree.cleanup_worktree(repo_root, task.id, wt_path, fleet_home=st.project_root)
        try:
            worktree.delete_branch(repo_root, task.id)
        except Exception:  # noqa: BLE001
            pass
    (task_dir / ".worktree").unlink(missing_ok=True)
    try:
        st.queue.clear_isolation_info(task.id)
    except Exception:  # noqa: BLE001
        pass


def apply_noop(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    decision: Decision,
    fleet_ctx: dict,
    status: str | None = None,
    result: Result | None = None,
) -> None:
    """Log a NOOP decision; no queue writes."""
    _ = (task_dir, status, result)
    st.log.info(
        "task_noop_on_exit",
        task_id=task.id,
        outcome=record.outcome.name,
        reason=decision.reason,
        **fleet_ctx,
    )


def apply_close(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    decision: Decision,
    fleet_ctx: dict,
    status: str | None = None,
    result: Result | None = None,
) -> None:
    """Close the bead; the worker's declared reason is the close reason."""
    _ = (task_dir, record, status, result)
    st.queue.close(task.id, reason=decision.reason)
    st.log.info("task_closed_by_fleet", task_id=task.id, **fleet_ctx)


def _log_block_outcome(
    st: SupervisorState,
    task: Task,
    record: TaskOutcomeRecord,
    decision: Decision,
    fleet_ctx: dict,
    result: Result | None,
) -> None:
    """Log which ladder rung blocked the bead."""
    outcome = record.outcome
    if outcome == TaskOutcome.FAILURE:
        note = f" Worker summary: {result.summary}" if result and result.summary else ""
        st.queue.comment(
            task.id,
            f"[fleet] {decision.reason} Last exit code={record.exit_code}. "
            f"stderr_tail: {record.stderr_tail}.{note}",
        )
        st.log.error("task_retry_exhausted", task_id=task.id, **fleet_ctx)
    elif outcome in (TaskOutcome.SUCCESS, TaskOutcome.PARTIAL):
        st.queue.comment(task.id, f"[fleet] {decision.reason}")
        st.log.warning("task_noclose_exhausted", task_id=task.id, **fleet_ctx)
    elif outcome == TaskOutcome.KILLED and record.reason in ("stalled", "timeout"):
        st.log.warning("task_stall_exhausted", task_id=task.id, **fleet_ctx)
    elif outcome == TaskOutcome.TERMINAL:
        st.queue.comment(task.id, f"[fleet] {decision.reason}")
        st.log.error("task_terminal", task_id=task.id, **fleet_ctx)
    elif outcome == TaskOutcome.KILLED:
        st.queue.comment(task.id, f"[fleet] {decision.reason}.")
        st.log.info("task_blocked", task_id=task.id, **fleet_ctx)
    else:
        st.log.info("task_blocked", task_id=task.id, **fleet_ctx)


def apply_block(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    decision: Decision,
    fleet_ctx: dict,
    status: str | None = None,
    result: Result | None = None,
) -> None:
    """Block the bead, unless the agent already blocked it itself."""
    _ = task_dir
    if record.outcome == TaskOutcome.BLOCKED_BY_AGENT and status == "blocked":
        st.log.info("task_blocked_by_agent", task_id=task.id, **fleet_ctx)
        return
    st.queue.set_blocked(task.id, decision.reason)
    _log_block_outcome(st, task, record, decision, fleet_ctx, result)


def _release_waiting(st: SupervisorState, task: Task, decision: Decision, fleet_ctx: dict) -> None:
    """Release a WAITING epic silently; the wait keeps it from hot-looping claim."""
    st.queue.release(task.id, reason="", wait_sec=decision.wait_sec or 0)
    st.log.info("worker_waiting", task_id=task.id, reason=decision.reason, **fleet_ctx)


def _release_rate_limit(
    st: SupervisorState, task: Task, record: TaskOutcomeRecord, decision: Decision, fleet_ctx: dict
) -> None:
    """Release a rate-limited task and pause claiming until the delay passes."""
    wait_sec = decision.wait_sec or 0
    st.queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
    sleep_until = datetime.now(tz=UTC) + timedelta(seconds=wait_sec)
    if st.paused_until is None or sleep_until > st.paused_until:
        st.paused_until = sleep_until
    rate_ctx = {k: v for k, v in fleet_ctx.items() if k != "paused_until"}
    st.log.warning(
        "task_rate_limit_release",
        task_id=task.id,
        resets_at=record.resets_at,
        paused_until=str(st.paused_until),
        **rate_ctx,
    )


def _release_stall(st: SupervisorState, task: Task, task_dir: Path, decision: Decision) -> None:
    """Release a stall-killed task for retry; the stall ladder counts the round."""
    wait_sec = decision.wait_sec or 0
    history = attempts.load_attempts(task_dir)
    rounds = retry_policy._trailing_streak(history, "stall") + 1
    st.queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
    st.log.warning("task_stall_handled", task_id=task.id, count=rounds)


def _release_failure(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    decision: Decision,
    result: Result | None,
) -> None:
    """Release a failed task for retry and comment the failure count."""
    wait_sec = decision.wait_sec or 0
    history = attempts.load_attempts(task_dir)
    rounds = retry_policy._trailing_streak(history, "failure") + 1
    note = f" Worker summary: {result.summary}" if result and result.summary else ""
    st.queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
    st.queue.comment(
        task.id,
        f"[fleet] failure {rounds} (rc={record.exit_code}). Releasing for retry.{note}",
    )
    st.log.warning("task_failure_release", task_id=task.id, failures=rounds)


def _release_partial(
    st: SupervisorState, task: Task, task_dir: Path, decision: Decision
) -> None:
    """Release a partial task for retry and comment the progress count."""
    wait_sec = decision.wait_sec or 0
    history = attempts.load_attempts(task_dir)
    rounds = retry_policy._trailing_streak(history, "partial") + 1
    st.queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
    st.queue.comment(
        task.id,
        f"[fleet] partial progress #{rounds}/{PARTIAL_MAX_ROUNDS}: {decision.reason}",
    )
    st.log.info("task_partial_release", task_id=task.id, count=rounds)


def _release_success(st: SupervisorState, task: Task, task_dir: Path, decision: Decision) -> None:
    """Release an rc=0 task that declared nothing, warning about the missing RESULT."""
    wait_sec = decision.wait_sec or 0
    history = attempts.load_attempts(task_dir)
    rounds = retry_policy._trailing_streak(history, "noclose") + 1
    st.queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
    st.queue.comment(
        task.id,
        f"[fleet] success #{rounds}/{NOCLOSE_MAX_ROUNDS}: rc=0, "
        f"worker exited without RESULT.json. "
        f"At {NOCLOSE_MAX_ROUNDS} the task will be blocked for human review.",
    )
    st.log.warning("task_success_noclose", task_id=task.id, count=rounds)


def _release_context(st: SupervisorState, task: Task, task_dir: Path, decision: Decision) -> None:
    """Release a context-pressured task for a compacted retry."""
    wait_sec = decision.wait_sec or 0
    history = attempts.load_attempts(task_dir)
    rounds = retry_policy._trailing_streak(history, "context") + 1
    st.queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
    st.queue.comment(
        task.id,
        f"[fleet] context limit round {rounds}/{CONTEXT_MAX_ROUNDS}; compaction + continue",
    )
    st.log.info("task_context_release", task_id=task.id, count=rounds)


def apply_release(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    decision: Decision,
    fleet_ctx: dict,
    status: str | None = None,
    result: Result | None = None,
) -> None:
    """Release the bead back to the queue along the rung its outcome names."""
    _ = status
    wait_sec = decision.wait_sec or 0
    outcome = record.outcome
    if outcome == TaskOutcome.WAITING:
        _release_waiting(st, task, decision, fleet_ctx)
    elif outcome == TaskOutcome.RATE_LIMIT:
        _release_rate_limit(st, task, record, decision, fleet_ctx)
    elif outcome == TaskOutcome.KILLED and record.reason in ("stalled", "timeout"):
        _release_stall(st, task, task_dir, decision)
    elif outcome == TaskOutcome.FAILURE:
        _release_failure(st, task, task_dir, record, decision, result)
    elif outcome == TaskOutcome.PARTIAL:
        _release_partial(st, task, task_dir, decision)
    elif outcome == TaskOutcome.SUCCESS:
        _release_success(st, task, task_dir, decision)
    elif outcome == TaskOutcome.CONTEXT_PRESSURE:
        _release_context(st, task, task_dir, decision)
    else:
        st.queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
        st.log.info("task_released", task_id=task.id, **fleet_ctx)


_APPLY = {
    Action.NOOP: apply_noop,
    Action.CLOSE: apply_close,
    Action.BLOCK: apply_block,
    Action.RELEASE: apply_release,
}


def apply_decision(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    decision: Decision,
    fleet_ctx: dict,
    status: str | None = None,
    result: Result | None = None,
) -> None:
    """Apply a retry-policy decision through the per-action function."""
    _drop_stale_counter_files(task_dir)
    _APPLY[decision.action](st, task, task_dir, record, decision, fleet_ctx, status, result)


def snapshot_attempt_artifacts(
    st: SupervisorState, task: Task, task_dir: Path, n: int
) -> None:
    """Copy this attempt's STATE.md/RESULT.json into attempts/<n>/ and unlink live RESULT."""
    attempt_dir = attempts.attempt_dir(task_dir, n)
    attempt_dir.mkdir(parents=True, exist_ok=True)

    state_src = task_dir / STATE_MD
    if state_src.exists():
        try:
            (attempt_dir / STATE_MD).write_bytes(state_src.read_bytes())
        except OSError as exc:
            st.log.warning("attempt_snapshot_failed", task_id=task.id, file=STATE_MD, error=str(exc))

    result_src = task_dir / RESULT_JSON
    if result_src.exists():
        try:
            (attempt_dir / RESULT_JSON).write_bytes(result_src.read_bytes())
        except OSError as exc:
            st.log.warning(
                "attempt_snapshot_failed", task_id=task.id, file=RESULT_JSON, error=str(exc)
            )
        try:
            result_src.unlink(missing_ok=True)
        except OSError as exc:
            st.log.warning("attempt_result_unlink_failed", task_id=task.id, error=str(exc))


def is_observer_run(task: Task, history: list[dict]) -> bool:
    """True when this attempt ran the observer worker (epic validation)."""
    if (task.type or "") == "epic":
        return True
    return bool(history and str(history[-1].get("worker") or "").startswith("observer"))


def observer_cap_decision(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    history: list[dict],
) -> Decision | None:
    """BLOCK an epic past its observer follow-up rounds, else None."""
    _ = task_dir
    if record.outcome != TaskOutcome.PARTIAL:
        return None
    if not is_observer_run(task, history):
        return None
    max_rounds = getattr(st.config, "observer_max_rounds", 3)
    if observer_rounds(history) + 1 >= max_rounds:
        return Decision(Action.BLOCK, reason="observer exhausted; needs human review")
    return None


def handle_outcome(
    st: SupervisorState, worker: RunningWorker, outcome: TaskOutcomeRecord
) -> None:
    """Fold one finished worker's outcome into queue state and the attempts journal."""
    task = worker.task
    task_dir = st.task_dir_for(task.id)
    fleet_ctx = fleet_log_context(st)
    status = bead_status(st, task.id)

    result = read_declared_result(task_dir)
    record = outcome

    decision = maybe_handle_isolated_success(st, task, task_dir, record, status, result)
    if decision is None:
        if record.outcome == TaskOutcome.SUCCESS and status == "blocked":
            record = TaskOutcomeRecord(
                outcome=TaskOutcome.BLOCKED_BY_AGENT,
                exit_code=record.exit_code,
                reason="agent set task to blocked",
            )
        elif record.outcome == TaskOutcome.SUCCESS and result is not None:
            record = fold_declared_result(record, result)
        history = attempts.load_attempts(task_dir)
        decision = observer_cap_decision(st, task, task_dir, record, history)
        if decision is None:
            decision = retry_policy.decide(record, history, status, st.config)
    apply_decision(st, task, task_dir, record, decision, fleet_ctx, status, result)

    try:
        attempts.record_end(
            task_dir,
            outcome=record.outcome.value,
            exit_code=record.exit_code,
            reason=record.reason,
            action=decision.action.value,
            n=worker.attempt_n,
        )
    except OSError as exc:
        st.log.warning("attempt_record_failed", task_id=task.id, error=str(exc))
        return

    n = worker.attempt_n or attempts.current_attempt_n(task_dir)
    if n > 0:
        snapshot_attempt_artifacts(st, task, task_dir, n)


class Reap(Service):
    """Collect finished workers and apply their outcomes, then notify services."""

    order = ServiceOrder.Reap
    name = "reap"

    async def serve(self, st: SupervisorState) -> None:
        """Wait for each future to finish and reap it until shutdown drains the set."""
        while not st.shutting_down or st.running:
            if not st.running:
                await asyncio.sleep(0.1)
                continue
            try:
                done, _ = await asyncio.wait(
                    [rw.future for rw in st.running.values()],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=1.0,
                )
            except (asyncio.CancelledError, ValueError):
                break
            for fut in done:
                worker = pop_finished(st, fut)
                if worker is None:
                    continue
                outcome = outcome_of(fut)
                if outcome.reason.startswith("unexpected exception: "):
                    st.log.error(
                        "runner_unexpected_exception",
                        task_id=worker.task.id,
                        error=outcome.reason,
                    )
                handle_outcome(st, worker, outcome)
                await emit(st.services, "on_worker_finished", st, worker, outcome)
