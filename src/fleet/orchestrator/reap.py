"""Reap service: collect finished workers, apply the outcome, notify the rest.

Reap is event-driven, not periodic: it waits for the first in-flight
future to finish, removes its RunningWorker from the shared state, folds
the outcome through the retry policy, and emits `on_worker_finished` so
other services (StallWatch) can drop their per-task scratch data.

Applying a decision is a table, not an if-chain: ``APPLY`` maps every
``Action`` to one small function taking ``(st, ctx, decision)``.
Isolated-worktree success splits into pure ``decide_isolated_success``
plus I/O ``apply_isolated_success``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.core import retry_policy
from fleet.core.isolation import IsolationInfo
from fleet.core.isolation import read as read_isolation
from fleet.core.result import ResultStatus, WorkerResult
from fleet.core.retry_policy import (
    CONTEXT_MAX_ROUNDS,
    NOCLOSE_MAX_ROUNDS,
    PARTIAL_MAX_ROUNDS,
    Action,
    RetryDecision,
)
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord, TaskStatus
from fleet.state import attempts
from fleet.state.artifacts import ResultFile, StateFile
from fleet.state.paths import attempt_dir
from fleet.state.validation_marker import set_needs_validation

from . import worktree
from .service import ServiceOrder, emit
from .status_log import task_log_fields

if TYPE_CHECKING:
    from .state import RunningWorker, SupervisorState

_STALE_COUNTER_FILES = (".failures", ".noclose", ".stalls")


@dataclass(frozen=True, slots=True)
class ReapContext:
    """Everything one apply-function needs about a finished worker."""

    task: Task
    task_dir: Path
    record: TaskOutcomeRecord
    bead_status: str | None
    result: WorkerResult | None


class IsolatedVerdict(StrEnum):
    """What an isolated (worktree) SUCCESS exit means, decided purely."""

    SKIP = "skip"
    NEEDS_VALIDATION = "needs_validation"
    DISCARD = "discard"
    RETRY = "retry"
    BLOCK = "block"


def _drop_stale_counter_files(task_dir: Path) -> None:
    """Remove pre-retry-policy counter files; rounds now come from attempts.jsonl."""
    for name in _STALE_COUNTER_FILES:
        with contextlib.suppress(OSError):
            (task_dir / name).unlink(missing_ok=True)


def pop_finished(st: SupervisorState, fut: asyncio.Task) -> RunningWorker | None:
    """Remove and return the RunningWorker that owns `fut`, or None when unknown."""
    task_id = next((tid for tid, rw in st.running.items() if rw.future is fut), None)
    if task_id is None:
        return None
    return st.running.pop(task_id)


def outcome_of(fut: asyncio.Task) -> TaskOutcomeRecord:
    """Unwrap a finished future into its outcome record, or None when it raised."""
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


def read_live_result(task_dir: Path) -> WorkerResult | None:
    """Parse the live task-level RESULT.json (the worker's declared outcome), if present."""
    return ResultFile.read_declared(task_dir)


def fold_declared_result(record: TaskOutcomeRecord, result: WorkerResult) -> TaskOutcomeRecord:
    """Fold a declared RESULT.json into an rc=0 outcome record."""
    if result.status == ResultStatus.DONE:
        return TaskOutcomeRecord(
            outcome=TaskOutcome.SUCCESS,
            exit_code=record.exit_code,
            reason=result.summary,
            close_reason=result.summary or "completed",
        )
    if result.status == ResultStatus.PARTIAL:
        return TaskOutcomeRecord(
            outcome=TaskOutcome.PARTIAL,
            exit_code=record.exit_code,
            reason=result.next_step or result.summary,
        )
    return TaskOutcomeRecord(
        outcome=TaskOutcome.BLOCKED_BY_CODER,
        exit_code=record.exit_code,
        reason=result.blocked_reason or result.summary,
    )


def decide_isolated_success(
    record: TaskOutcomeRecord,
    bead_status: str | None,
    result: WorkerResult | None,
    info: IsolationInfo | None,
    history: list[dict],
    committed_clean: bool,
    has_changes: bool,
) -> tuple[IsolatedVerdict, RetryDecision | None]:
    """Decide an isolated (worktree) SUCCESS exit purely; no I/O.

    Returns the verdict plus the RetryDecision to apply for RETRY/BLOCK
    (None for the verdicts the caller handles with side effects).
    """
    if record.outcome != TaskOutcome.SUCCESS or bead_status != TaskStatus.IN_PROGRESS.value:
        return IsolatedVerdict.SKIP, None
    if info is None:
        return IsolatedVerdict.SKIP, None
    if result is None or result.status != ResultStatus.DONE:
        return IsolatedVerdict.SKIP, None
    if committed_clean:
        return IsolatedVerdict.NEEDS_VALIDATION, RetryDecision(
            Action.NOOP, reason="needs validation"
        )
    if not has_changes:
        return IsolatedVerdict.DISCARD, None
    rounds = retry_policy.trailing_streak(history, "noclose") + 1
    return _uncommitted_verdict(info.worktree_path, rounds)


def _uncommitted_verdict(
    worktree_path: str, rounds: int
) -> tuple[IsolatedVerdict, RetryDecision | None]:
    """BLOCK past the no-close cap, else RELEASE asking for a commit."""
    detail = f"uncommitted changes left in {worktree_path}"
    if rounds >= NOCLOSE_MAX_ROUNDS:
        return IsolatedVerdict.BLOCK, RetryDecision(
            Action.BLOCK,
            reason=(
                f"isolated task exited without a clean commit ({detail}) "
                f"({rounds}/{NOCLOSE_MAX_ROUNDS}); needs human review"
            ),
        )
    return IsolatedVerdict.RETRY, RetryDecision(
        Action.RELEASE,
        reason=(
            f"isolated task exited without a clean commit ({detail}) "
            f"(#{rounds}/{NOCLOSE_MAX_ROUNDS}); commit or revert them"
        ),
        wait_sec=0,
    )


def apply_isolated_success(
    st: SupervisorState, ctx: ReapContext, info: IsolationInfo, verdict: IsolatedVerdict
) -> None:
    """Apply an isolated-success verdict's side effects (marker, worktree, queue)."""
    log = st.log.bind(**task_log_fields(ctx.task))
    if verdict is IsolatedVerdict.NEEDS_VALIDATION:
        set_needs_validation(ctx.task_dir)
        log.info("task.needs_validation")
    elif verdict is IsolatedVerdict.DISCARD:
        log.info("task.isolated_no_repo_changes")
        discard_isolation(st, ctx.task, ctx.task_dir, info)


def snapshot_isolated_artifacts(
    st: SupervisorState, ctx: ReapContext, info: IsolationInfo, verdict: IsolatedVerdict
) -> None:
    """File side effects of an isolated SUCCESS: validation marker or cleanup."""
    _ = info
    if verdict is IsolatedVerdict.SKIP:
        return
    apply_isolated_success(st, ctx, info, verdict)


def discard_isolation(st: SupervisorState, task: Task, task_dir: Path, info: IsolationInfo) -> None:
    """Remove a worktree that carries no work and forget the isolation info."""
    wt_path = Path(info.worktree_path)
    if info.repo_root:
        worktree.cleanup_worktree(info.repo_root, task.id, wt_path, fleet_home=st.fleet_home)
        with contextlib.suppress(Exception):  # noqa: BLE001
            worktree.delete_branch(info.repo_root, task.id)
    (task_dir / ".worktree").unlink(missing_ok=True)
    with contextlib.suppress(Exception):  # noqa: BLE001
        st.queue.clear_isolation_info(task.id)


def apply_noop(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Log a NOOP decision; no queue writes."""
    st.log.bind(**task_log_fields(ctx.task)).info(
        "task_noop_on_exit",
        outcome=ctx.record.outcome.name,
        reason=decision.reason,
    )


def apply_close(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Close the bead; the worker's declared reason is the close reason."""
    st.queue.close(ctx.task.id, reason=decision.reason)
    st.log.bind(**task_log_fields(ctx.task)).info("task_closed_by_fleet")


def apply_block(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Block the bead, unless the agent already blocked it itself."""
    log = st.log.bind(**task_log_fields(ctx.task))
    if (
        ctx.record.outcome == TaskOutcome.BLOCKED_BY_CODER
        and ctx.bead_status == TaskStatus.BLOCKED.value
    ):
        log.info("task_blocked_by_coder")
        return
    st.queue.set_blocked(ctx.task.id, decision.reason)
    _log_block_outcome(st, ctx, decision)


def _log_block_outcome(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Log which ladder rung blocked the bead."""
    log = st.log.bind(**task_log_fields(ctx.task))
    outcome = ctx.record.outcome
    if outcome == TaskOutcome.FAILURE:
        note = f" Worker summary: {ctx.result.summary}" if ctx.result and ctx.result.summary else ""
        st.queue.comment(
            ctx.task.id,
            f"[fleet] {decision.reason} Last exit code={ctx.record.exit_code}. "
            f"stderr_tail: {ctx.record.stderr_tail}.{note}",
        )
        log.error("task_retry_exhausted")
    elif outcome in (TaskOutcome.SUCCESS, TaskOutcome.PARTIAL):
        st.queue.comment(ctx.task.id, f"[fleet] {decision.reason}")
        log.warning("task_noclose_exhausted")
    elif outcome == TaskOutcome.KILLED and ctx.record.reason in ("stalled", "timeout"):
        log.warning("task_stall_exhausted")
    elif outcome == TaskOutcome.TERMINAL:
        st.queue.comment(ctx.task.id, f"[fleet] {decision.reason}")
        log.error("task_terminal")
    elif outcome == TaskOutcome.KILLED:
        st.queue.comment(ctx.task.id, f"[fleet] {decision.reason}.")
        log.info("task_blocked")
    else:
        log.info("task_blocked")


def _release_waiting(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Release a WAITING epic silently; the wait keeps it from hot-looping claim."""
    st.queue.release(ctx.task.id, reason="", wait_sec=decision.wait_sec or 0)
    st.log.bind(**task_log_fields(ctx.task)).info("worker_waiting", reason=decision.reason)


def _release_rate_limit(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Release a rate-limited task and pause claiming until the delay passes."""
    wait_sec = decision.wait_sec or 0
    st.queue.release(ctx.task.id, reason=decision.reason, wait_sec=wait_sec)
    sleep_until = st.clock.now() + timedelta(seconds=wait_sec)
    if st.paused_until is None or sleep_until > st.paused_until:
        st.paused_until = sleep_until
    st.log.bind(**task_log_fields(ctx.task)).warning(
        "task_rate_limit_release",
        resets_at=ctx.record.resets_at,
        paused_until=str(st.paused_until),
    )


def _release_stall(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Release a stall-killed task for retry; the stall ladder counts the round."""
    history = attempts.load_attempts(ctx.task_dir)
    rounds = retry_policy.trailing_streak(history, "stall") + 1
    st.queue.release(ctx.task.id, reason=decision.reason, wait_sec=decision.wait_sec or 0)
    st.log.bind(**task_log_fields(ctx.task)).warning("task_stall_handled", count=rounds)


def _release_failure(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Release a failed task for retry and comment the failure count."""
    history = attempts.load_attempts(ctx.task_dir)
    rounds = retry_policy.trailing_streak(history, "failure") + 1
    note = f" Worker summary: {ctx.result.summary}" if ctx.result and ctx.result.summary else ""
    st.queue.release(ctx.task.id, reason=decision.reason, wait_sec=decision.wait_sec or 0)
    st.queue.comment(
        ctx.task.id,
        f"[fleet] failure {rounds} (rc={ctx.record.exit_code}). Releasing for retry.{note}",
    )
    st.log.bind(**task_log_fields(ctx.task)).warning("task_failure_release", failures=rounds)


def _release_partial(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Release a partial task for retry and comment the progress count."""
    history = attempts.load_attempts(ctx.task_dir)
    rounds = retry_policy.trailing_streak(history, "partial") + 1
    st.queue.release(ctx.task.id, reason=decision.reason, wait_sec=decision.wait_sec or 0)
    st.queue.comment(
        ctx.task.id,
        f"[fleet] partial progress #{rounds}/{PARTIAL_MAX_ROUNDS}: {decision.reason}",
    )
    st.log.bind(**task_log_fields(ctx.task)).info("task_partial_release", count=rounds)


def _release_success(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Release an rc=0 task that declared nothing, warning about the missing RESULT."""
    history = attempts.load_attempts(ctx.task_dir)
    rounds = retry_policy.trailing_streak(history, "noclose") + 1
    st.queue.release(ctx.task.id, reason=decision.reason, wait_sec=decision.wait_sec or 0)
    st.queue.comment(
        ctx.task.id,
        f"[fleet] success #{rounds}/{NOCLOSE_MAX_ROUNDS}: rc=0, "
        f"worker exited without RESULT.json. "
        f"At {NOCLOSE_MAX_ROUNDS} the task will be blocked for human review.",
    )
    st.log.bind(**task_log_fields(ctx.task)).warning("task_success_noclose", count=rounds)


def _release_context(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Release a context-pressured task for a compacted retry."""
    history = attempts.load_attempts(ctx.task_dir)
    rounds = retry_policy.trailing_streak(history, "context") + 1
    st.queue.release(ctx.task.id, reason=decision.reason, wait_sec=decision.wait_sec or 0)
    st.queue.comment(
        ctx.task.id,
        f"[fleet] context limit round {rounds}/{CONTEXT_MAX_ROUNDS}; compaction + continue",
    )
    st.log.bind(**task_log_fields(ctx.task)).info("task_context_release", count=rounds)


def apply_release(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Release the bead back to the queue along the rung its outcome names."""
    outcome = ctx.record.outcome
    if outcome == TaskOutcome.WAITING:
        _release_waiting(st, ctx, decision)
    elif outcome == TaskOutcome.RATE_LIMIT:
        _release_rate_limit(st, ctx, decision)
    elif outcome == TaskOutcome.KILLED and ctx.record.reason in ("stalled", "timeout"):
        _release_stall(st, ctx, decision)
    elif outcome == TaskOutcome.FAILURE:
        _release_failure(st, ctx, decision)
    elif outcome == TaskOutcome.PARTIAL:
        _release_partial(st, ctx, decision)
    elif outcome == TaskOutcome.SUCCESS:
        _release_success(st, ctx, decision)
    elif outcome == TaskOutcome.CONTEXT_PRESSURE:
        _release_context(st, ctx, decision)
    else:
        st.queue.release(ctx.task.id, reason=decision.reason, wait_sec=decision.wait_sec or 0)
        st.log.bind(**task_log_fields(ctx.task)).info("task_released")


APPLY: dict[Action, Callable[[SupervisorState, ReapContext, RetryDecision], None]] = {
    Action.NOOP: apply_noop,
    Action.CLOSE: apply_close,
    Action.BLOCK: apply_block,
    Action.RELEASE: apply_release,
}


def apply_decision(st: SupervisorState, ctx: ReapContext, decision: RetryDecision) -> None:
    """Apply a retry-policy decision through the per-action function."""
    _drop_stale_counter_files(ctx.task_dir)
    APPLY[decision.action](st, ctx, decision)


def snapshot_attempt_artifacts(
    st: SupervisorState, task: Task, task_dir: Path, attempt_no: int
) -> None:
    """Copy this attempt's STATE.md/RESULT.json aside and unlink live RESULT."""
    adir = attempt_dir(task_dir, attempt_no)
    adir.mkdir(parents=True, exist_ok=True)

    try:
        StateFile.snapshot(task_dir, adir)
    except OSError as exc:
        st.log.warning("attempt_snapshot_failed", task_id=task.id, file="STATE.md", error=str(exc))

    try:
        ResultFile.snapshot(task_dir, adir)
    except OSError as exc:
        st.log.warning(
            "attempt_snapshot_failed", task_id=task.id, file="RESULT.json", error=str(exc)
        )


def _decide_full(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    status: str | None,
    result: WorkerResult | None,
) -> tuple[TaskOutcomeRecord, RetryDecision, IsolationInfo | None, IsolatedVerdict]:
    """Decide record + decision plus the isolated-worktree verdict behind them."""
    history = attempts.load_attempts(task_dir)
    info = read_isolation(task_dir)
    verdict, isolated_decision = decide_isolated_success(
        record,
        status,
        result,
        info,
        history,
        committed_clean=_worktree_committed_clean(info),
        has_changes=_worktree_has_changes(info),
    )
    if verdict is not IsolatedVerdict.SKIP and verdict is not IsolatedVerdict.DISCARD:
        assert isolated_decision is not None
        return record, isolated_decision, info, verdict
    # DISCARD falls through: the empty worktree is dropped (by the caller)
    # and the declared DONE folds like a plain in-place success.
    if record.outcome == TaskOutcome.SUCCESS and status == TaskStatus.BLOCKED.value:
        record = TaskOutcomeRecord(
            outcome=TaskOutcome.BLOCKED_BY_CODER,
            exit_code=record.exit_code,
            reason="coder set task to blocked",
        )
    elif record.outcome == TaskOutcome.SUCCESS and result is not None:
        record = fold_declared_result(record, result)
    capped = retry_policy.observer_cap_decision(
        task, record, history, max_rounds=st.config.observer_max_rounds
    )
    if capped is None:
        capped = retry_policy.decide(record, history, status, st.config, now=st.clock.now())
    return record, capped, info, verdict


def decide_outcome(
    st: SupervisorState,
    task: Task,
    task_dir: Path,
    record: TaskOutcomeRecord,
    status: str | None,
    result: WorkerResult | None,
) -> tuple[TaskOutcomeRecord, RetryDecision]:
    """Decide the folded record and retry-policy decision for a finished worker.

    Pure decision step: isolated-worktree success, blocked-fold of a SUCCESS
    exit, observer follow-up cap, then the retry-policy table. Queue writes
    happen in ``apply_decision``; journaling in ``handle_outcome``.
    """
    record, decision, _, _ = _decide_full(st, task, task_dir, record, status, result)
    return record, decision


def _worktree_committed_clean(info: IsolationInfo | None) -> bool:
    """Whether the isolated worktree is clean and ahead (False when unknown)."""
    if info is None:
        return False
    wt_path = Path(info.worktree_path)
    if not wt_path.is_dir():
        return False
    return worktree.is_committed_clean(wt_path, base_ref=info.base_ref or "main")


def _worktree_has_changes(info: IsolationInfo | None) -> bool:
    """Whether the isolated worktree holds uncommitted changes (True when unknown)."""
    if info is None:
        return False
    wt_path = Path(info.worktree_path)
    if not wt_path.is_dir():
        return False
    return worktree.has_uncommitted_changes(wt_path)


def handle_outcome(st: SupervisorState, worker: RunningWorker, outcome: TaskOutcomeRecord) -> None:
    """Fold one finished worker's outcome into queue state and the attempts journal."""
    task = worker.task
    task_dir = st.task_dir_for(task.id)
    status = bead_status(st, task.id)

    result = read_live_result(task_dir)
    record, decision, info, verdict = _decide_full(st, task, task_dir, outcome, status, result)
    ctx = ReapContext(
        task=task, task_dir=task_dir, record=record, bead_status=status, result=result
    )
    if info is not None and verdict is not IsolatedVerdict.SKIP:
        snapshot_isolated_artifacts(st, ctx, info, verdict)
    apply_decision(st, ctx, decision)

    try:
        attempts.record_end(
            task_dir,
            outcome=record.outcome,
            exit_code=record.exit_code,
            reason=record.reason,
            action=decision.action,
            attempt_no=worker.attempt_n,
        )
    except OSError as exc:
        st.log.warning("attempt_record_failed", task_id=task.id, error=str(exc))
        return

    n = worker.attempt_n or attempts.current_attempt_n(task_dir)
    if n > 0:
        snapshot_attempt_artifacts(st, task, task_dir, n)


class Reap:
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
