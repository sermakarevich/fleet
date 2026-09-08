from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.core import outcome_policy
from fleet.core.limits import NOCLOSE_LIMIT, RETRY_LIMIT
from fleet.core.outcome_policy import Action, Counters, Decision
from fleet.core.result import Result, parse_result
from fleet.core.task import Task, TaskOutcome, TaskOutcomeRecord
from fleet.state import attempts
from fleet.state.counters import (
    failure_count,
    increment_failure,
    increment_noclose,
    increment_stall,
    noclose_count,
    reset_failure,
    reset_noclose,
    reset_stall,
    set_needs_validation,
    stall_count,
)

from . import worktree


class ReapMixin:
    async def _reap_loop(self) -> None:
        while not self._shutting_down or self.in_flight:
            if not self.in_flight:
                await asyncio.sleep(0.1)
                continue

            try:
                done, _ = await asyncio.wait(
                    list(self.in_flight.values()),
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=1.0,
                )
            except (asyncio.CancelledError, ValueError):
                break

            for async_task in done:
                task_id = next(
                    (tid for tid, t in self.in_flight.items() if t is async_task),
                    None,
                )
                if task_id is None:
                    continue

                bead_task = self.in_flight_tasks.pop(task_id)
                self.in_flight.pop(task_id)
                self._runners.pop(task_id, None)
                self._stall_warned.discard(task_id)
                self._stall_killed.discard(task_id)

                try:
                    outcome: TaskOutcomeRecord = async_task.result()
                except Exception as exc:
                    self._log.error(
                        "runner_unexpected_exception",
                        task_id=task_id,
                        error=str(exc),
                    )
                    outcome = TaskOutcomeRecord(
                        outcome=TaskOutcome.FAILURE,
                        reason=f"unexpected exception: {exc}",
                    )

                self._handle_outcome(bead_task, outcome)

    def _bead_status(self, task_id: str) -> str | None:
        try:
            return self._queue.get(task_id).status
        except Exception:
            return None

    def _read_declared_result(self, task_dir: Path) -> Result | None:
        """Parse artifacts/RESULT.json, the worker's declared outcome, if present."""
        result_file = task_dir / "artifacts" / "RESULT.json"
        try:
            text = result_file.read_text(encoding="utf-8")
        except OSError:
            return None
        return parse_result(text)

    def _fold_declared_result(
        self, record: TaskOutcomeRecord, result: Result
    ) -> TaskOutcomeRecord:
        """Fold a declared RESULT.json into the rc=0 outcome record.

        Only called for rc=0 exits: a nonzero exit code is always FAILURE
        regardless of what RESULT.json says.
        """
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
        # status == "blocked"
        return TaskOutcomeRecord(
            outcome=TaskOutcome.BLOCKED_BY_AGENT,
            exit_code=record.exit_code,
            reason=result.blocked_reason or result.summary,
        )

    def _counters_for(self, task_dir: Path) -> Counters:
        return Counters(
            failures=failure_count(task_dir),
            noclose=noclose_count(task_dir),
            stalls=stall_count(task_dir),
        )

    def _maybe_handle_isolated_success(
        self, task: Task, task_dir: Path, record: TaskOutcomeRecord, bead_status: str | None
    ) -> bool:
        """Handle a SUCCESS exit for an isolated (worktree) task.

        Requires reading git state, so it cannot live in the pure policy.
        Returns True when it fully handled the outcome (caller should not
        also call outcome_policy.decide()).
        """
        if record.outcome != TaskOutcome.SUCCESS or bead_status != "in_progress":
            return False
        wt_marker = task_dir / ".worktree"
        if not wt_marker.exists():
            return False

        wt_path = Path(wt_marker.read_text().strip())
        if worktree.is_committed_clean(wt_path, base_ref="main"):
            set_needs_validation(task_dir)
            self._log.info("task.needs_validation", task_id=task.id)
            return True

        count = increment_noclose(task_dir)
        reason = f"isolated task exited without a clean commit ({count}x)"
        if count >= NOCLOSE_LIMIT:
            self._queue.set_blocked(task.id, reason)
        else:
            self._queue.release(task.id)
        return True

    def _apply_decision(
        self,
        task: Task,
        task_dir: Path,
        record: TaskOutcomeRecord,
        decision: Decision,
        fleet_ctx: dict,
        bead_status: str | None = None,
        result: Result | None = None,
    ) -> None:
        outcome = record.outcome

        if decision.action == Action.NOOP:
            if outcome == TaskOutcome.SUCCESS:
                reset_noclose(task_dir)
                reset_stall(task_dir)
                self._log.info("task_completed_success", task_id=task.id, **fleet_ctx)
            else:
                reset_failure(task_dir)
                self._log.info(
                    "task_already_closed_on_exit",
                    task_id=task.id,
                    outcome=outcome.name,
                    **fleet_ctx,
                )
            return

        if outcome == TaskOutcome.SUCCESS and decision.action == Action.CLOSE:
            self._queue.close(task.id, reason=decision.reason)
            reset_noclose(task_dir)
            reset_stall(task_dir)
            self._log.info("task_closed_by_fleet", task_id=task.id, **fleet_ctx)
            return

        if outcome == TaskOutcome.SUCCESS:
            # No RESULT.json (or fleet would have taken the CLOSE branch above).
            count = increment_noclose(task_dir)
            if decision.action == Action.BLOCK:
                self._queue.set_blocked(task.id, decision.reason)
                self._queue.comment(
                    task.id,
                    f"[fleet] no-close limit exhausted: {count} successful exits, "
                    f"worker exited without RESULT.json. Blocked for human review.",
                )
                self._log.warning(
                    "task_noclose_exhausted", task_id=task.id, count=count, limit=NOCLOSE_LIMIT
                )
            else:  # RELEASE
                self._queue.release(task.id, reason=decision.reason)
                self._queue.comment(
                    task.id,
                    f"[fleet] success #{count}/{NOCLOSE_LIMIT}: rc=0, "
                    f"worker exited without RESULT.json. "
                    f"At {NOCLOSE_LIMIT} the task will be blocked for human review.",
                )
                self._log.warning(
                    "task_success_noclose", task_id=task.id, count=count, limit=NOCLOSE_LIMIT
                )
            return

        if outcome == TaskOutcome.PARTIAL:
            count = increment_noclose(task_dir)
            if decision.action == Action.BLOCK:
                self._queue.set_blocked(task.id, decision.reason)
                self._queue.comment(
                    task.id,
                    f"[fleet] no-close limit exhausted: {count} partial exits. "
                    f"Blocked for human review.",
                )
                self._log.warning(
                    "task_partial_exhausted", task_id=task.id, count=count, limit=NOCLOSE_LIMIT
                )
            else:  # RELEASE
                self._queue.release(task.id, reason=decision.reason)
                self._queue.comment(
                    task.id,
                    f"[fleet] partial progress #{count}/{NOCLOSE_LIMIT}: {decision.reason}",
                )
                self._log.info(
                    "task_partial_release", task_id=task.id, count=count, limit=NOCLOSE_LIMIT
                )
            return

        if outcome == TaskOutcome.CONTEXT_PRESSURE:
            # decision.action == RELEASE_FOR_CONTEXT
            self._queue.release(task.id, reason=decision.reason)
            self._log.info("task_context_pressure_release", task_id=task.id, **fleet_ctx)
            return

        if outcome == TaskOutcome.RATE_LIMIT:
            # decision.action == RELEASE_AFTER_RATE_LIMIT
            self._queue.release(task.id, reason=decision.reason)
            now = datetime.now(tz=UTC)
            sleep_sec = decision.sleep_sec or 0
            sleep_until = now + timedelta(seconds=sleep_sec)
            if self._paused_until is None or sleep_until > self._paused_until:
                self._paused_until = sleep_until
            rate_ctx = {k: v for k, v in fleet_ctx.items() if k != "paused_until"}
            self._log.warning(
                "task_rate_limit_release",
                task_id=task.id,
                resets_at=record.resets_at,
                paused_until=str(self._paused_until),
                **rate_ctx,
            )
            return

        if outcome == TaskOutcome.BLOCKED_BY_AGENT:
            if bead_status != "blocked":
                # Declared via RESULT.json (status=blocked): the bead itself
                # is still in_progress, so fleet has to block it.
                self._queue.set_blocked(task.id, decision.reason)
            # else: the agent already called `fleet bd block` itself.
            self._log.info("task_blocked_by_agent", task_id=task.id, **fleet_ctx)
            return

        if outcome == TaskOutcome.KILLED:
            if record.reason == "stalled":
                self._stall_killed.discard(task.id)
                count = increment_stall(task_dir)
                if decision.action == Action.BLOCK:
                    self._queue.set_blocked(task.id, decision.reason)
                else:  # RELEASE
                    self._queue.release(task.id, reason=decision.reason)
                self._log.warning("task_stall_handled", task_id=task.id, count=count)
                return
            # decision.action == BLOCK: manually interrupted
            self._queue.set_blocked(task.id, reason="manually interrupted")
            self._queue.comment(task.id, "[fleet] task was manually interrupted.")
            self._log.info("task_killed", task_id=task.id, **fleet_ctx)
            return

        if outcome == TaskOutcome.FAILURE:
            count = increment_failure(task_dir)
            result_note = f" Worker summary: {result.summary}" if result and result.summary else ""
            if decision.action == Action.BLOCK:
                self._queue.set_blocked(task.id, reason=decision.reason)
                self._queue.comment(
                    task.id,
                    (
                        f"[fleet] retry limit exhausted after {count} failures. "
                        f"Last exit code={record.exit_code}. "
                        f"stderr_tail: {record.stderr_tail}.{result_note}"
                    ),
                )
                self._log.error(
                    "task_retry_exhausted",
                    task_id=task.id,
                    failures=count,
                    retry_limit=RETRY_LIMIT,
                    **fleet_ctx,
                )
            else:  # RELEASE
                self._queue.release(task.id, reason=decision.reason)
                self._queue.comment(
                    task.id,
                    f"[fleet] failure {count} (rc={record.exit_code}). "
                    f"Releasing for retry.{result_note}",
                )
                self._log.warning(
                    "task_failure_release",
                    task_id=task.id,
                    failures=count,
                    retry_limit=RETRY_LIMIT,
                    **fleet_ctx,
                )
            return

    def _handle_outcome(self, task: Task, outcome: TaskOutcomeRecord) -> None:
        task_dir = self._task_dir_for(task)
        fleet_ctx = self._fleet_log_context()
        bead_status = self._bead_status(task.id)

        result = self._read_declared_result(task_dir)

        handled = self._maybe_handle_isolated_success(task, task_dir, outcome, bead_status)
        if not handled:
            record = outcome
            if record.outcome == TaskOutcome.SUCCESS and bead_status == "blocked":
                record = TaskOutcomeRecord(
                    outcome=TaskOutcome.BLOCKED_BY_AGENT,
                    exit_code=record.exit_code,
                    reason="agent set task to blocked",
                )
            elif record.outcome == TaskOutcome.SUCCESS and result is not None:
                record = self._fold_declared_result(record, result)
            counters = self._counters_for(task_dir)
            decision = outcome_policy.decide(record, counters, bead_status, self.config)
            self._apply_decision(
                task, task_dir, record, decision, fleet_ctx, bead_status=bead_status, result=result
            )

        try:
            raw = (task_dir / "task.json").read_text(encoding="utf-8")
            status = json.loads(raw).get("status")
        except (OSError, ValueError):
            status = None
        action = {
            "open": "released",
            "blocked": "blocked",
            "closed": "closed",
        }.get(status if isinstance(status, str) else "", "unknown")
        try:
            attempts.record_end(
                task_dir,
                outcome=outcome.outcome.value,
                exit_code=outcome.exit_code,
                reason=outcome.reason,
                action=action,
            )
        except OSError as exc:
            self._log.warning(
                "attempt_record_failed", task_id=task.id, error=str(exc)
            )
