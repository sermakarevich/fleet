from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet.core import retry_policy
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
from fleet.state.attempt_summary import write_summary
from fleet.state.validation_marker import set_needs_validation

from . import worktree

_STALE_COUNTER_FILES = (".failures", ".noclose", ".stalls")


def _read_isolation_info(task_dir: Path) -> dict | None:
    """Read repo_root/base_ref/worktree_path from task.json, or None.

    Falls back to the legacy `.worktree` marker (worktree path only) for
    task dirs written before the task.json contract.
    """
    try:
        meta = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if isinstance(meta, dict):
        repo_root = meta.get("repo_root")
        base_ref = meta.get("base_ref")
        worktree_path = meta.get("worktree_path")
        if repo_root and base_ref and worktree_path:
            return {
                "repo_root": repo_root,
                "base_ref": base_ref,
                "worktree_path": worktree_path,
            }
    try:
        marker = task_dir / ".worktree"
        if marker.exists():
            text = marker.read_text(encoding="utf-8").strip()
            if text:
                meta_base = meta.get("base_ref") if isinstance(meta, dict) else None
                meta_repo = meta.get("repo_root") if isinstance(meta, dict) else None
                return {
                    "repo_root": meta_repo or "",
                    "base_ref": meta_base or "main",
                    "worktree_path": text,
                }
    except OSError:
        pass
    return None


def _resolve_workdir(task: Task, task_dir: Path) -> Path | None:
    """Best-effort workdir for summaries: isolated worktree, else task.cwd."""
    info = _read_isolation_info(task_dir)
    if info and info.get("worktree_path"):
        return Path(info["worktree_path"])
    if task.cwd:
        return Path(task.cwd)
    return None


def _drop_stale_counter_files(task_dir: Path) -> None:
    """Remove pre-retry-policy counter files; rounds now come from attempts.jsonl."""
    for name in _STALE_COUNTER_FILES:
        try:
            (task_dir / name).unlink(missing_ok=True)
        except OSError:
            pass


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
                attempt_n = self._attempt_n.pop(task_id, None)
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

                self._handle_outcome(bead_task, outcome, attempt_n=attempt_n)

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

    def _maybe_handle_isolated_success(
        self,
        task: Task,
        task_dir: Path,
        record: TaskOutcomeRecord,
        bead_status: str | None,
        result: Result | None = None,
    ) -> Decision | None:
        """Handle a SUCCESS exit for an isolated (worktree) task.

        Requires reading git state, so it cannot live in the pure policy.
        Returns a Decision when it handled the outcome, else None.

        Isolated tasks need validation only when the worker declared
        RESULT.json status=done AND the worktree is clean and ahead of base.
        A clean worktree with no commits means the task changed nothing in
        this repo (research, knowledge-base work, a no-op fix): a commit is
        not required, the worktree is dropped and the task closes like a
        non-isolated one. Only uncommitted changes left behind trigger the
        "commit your work" retry rounds, because removing the worktree would
        discard them. Anything else falls through to the normal retry policy.
        """
        if record.outcome != TaskOutcome.SUCCESS or bead_status != "in_progress":
            return None
        info = _read_isolation_info(task_dir)
        if info is None:
            return None
        if result is None or result.status != "done":
            return None

        wt_path = Path(info["worktree_path"])
        base_ref = info.get("base_ref") or "main"
        if worktree.is_committed_clean(wt_path, base_ref=base_ref):
            set_needs_validation(task_dir)
            self._log.info("task.needs_validation", task_id=task.id)
            return Decision(Action.NOOP, reason="needs validation")

        if not worktree.has_uncommitted_changes(wt_path):
            # Clean and not ahead of base: nothing to merge. Drop the
            # worktree and let the declared "done" close the task.
            self._log.info("task.isolated_no_repo_changes", task_id=task.id)
            self._discard_isolation(task, task_dir, info)
            return None

        history = attempts.load_attempts(task_dir)
        rounds = retry_policy._trailing_streak(history, "noclose") + 1
        detail = f"uncommitted changes left in {wt_path}"
        if rounds >= NOCLOSE_MAX_ROUNDS:
            reason = (
                f"isolated task exited without a clean commit ({detail}) "
                f"({rounds}/{NOCLOSE_MAX_ROUNDS}); needs human review"
            )
            return Decision(Action.BLOCK, reason=reason)
        return Decision(
            Action.RELEASE,
            reason=(
                f"isolated task exited without a clean commit ({detail}) "
                f"(#{rounds}/{NOCLOSE_MAX_ROUNDS}); commit or revert them"
            ),
            wait_sec=0,
        )

    def _discard_isolation(self, task: Task, task_dir: Path, info: dict) -> None:
        """Remove a worktree that carries no work and forget the isolation info."""
        repo_root = info.get("repo_root") or ""
        wt_path = Path(info["worktree_path"])
        if repo_root:
            worktree.cleanup_worktree(
                repo_root, task.id, wt_path, fleet_home=self._project_root
            )
            try:
                worktree.delete_branch(repo_root, task.id)
            except Exception:  # noqa: BLE001
                pass
        (task_dir / ".worktree").unlink(missing_ok=True)
        try:
            self._queue.clear_isolation_info(task.id)
        except Exception:  # noqa: BLE001
            pass

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
        _drop_stale_counter_files(task_dir)

        if decision.action == Action.NOOP:
            self._log.info(
                "task_noop_on_exit",
                task_id=task.id,
                outcome=outcome.name,
                reason=decision.reason,
                **fleet_ctx,
            )
            return

        if decision.action == Action.CLOSE:
            self._queue.close(task.id, reason=decision.reason)
            self._log.info("task_closed_by_fleet", task_id=task.id, **fleet_ctx)
            return

        if decision.action == Action.BLOCK:
            if outcome == TaskOutcome.BLOCKED_BY_AGENT and bead_status == "blocked":
                # The agent already called `fleet bd block` itself; the bead
                # is where it should be. No further queue writes.
                self._log.info("task_blocked_by_agent", task_id=task.id, **fleet_ctx)
                return
            self._queue.set_blocked(task.id, decision.reason)
            if outcome == TaskOutcome.FAILURE:
                note = f" Worker summary: {result.summary}" if result and result.summary else ""
                self._queue.comment(
                    task.id,
                    (
                        f"[fleet] {decision.reason} "
                        f"Last exit code={record.exit_code}. "
                        f"stderr_tail: {record.stderr_tail}.{note}"
                    ),
                )
                self._log.error("task_retry_exhausted", task_id=task.id, **fleet_ctx)
            elif outcome in (TaskOutcome.SUCCESS, TaskOutcome.PARTIAL):
                self._queue.comment(task.id, f"[fleet] {decision.reason}")
                self._log.warning("task_noclose_exhausted", task_id=task.id, **fleet_ctx)
            elif outcome == TaskOutcome.KILLED and record.reason in ("stalled", "timeout"):
                self._stall_killed.discard(task.id)
                self._log.warning("task_stall_exhausted", task_id=task.id, **fleet_ctx)
            elif outcome == TaskOutcome.TERMINAL:
                self._queue.comment(task.id, f"[fleet] {decision.reason}")
                self._log.error("task_terminal", task_id=task.id, **fleet_ctx)
            elif outcome == TaskOutcome.KILLED:
                # Manual kill: journal the interruption on the bead.
                self._queue.comment(task.id, f"[fleet] {decision.reason}.")
                self._log.info("task_blocked", task_id=task.id, **fleet_ctx)
            else:
                self._log.info("task_blocked", task_id=task.id, **fleet_ctx)
            return

        # RELEASE (possibly with a wait_sec delay stored as task.json retry_after).
        wait_sec = decision.wait_sec or 0
        if outcome == TaskOutcome.RATE_LIMIT:
            self._queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
            now = datetime.now(tz=UTC)
            sleep_until = now + timedelta(seconds=wait_sec)
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

        if outcome == TaskOutcome.KILLED and record.reason in ("stalled", "timeout"):
            self._stall_killed.discard(task.id)
            history = attempts.load_attempts(task_dir)
            rounds = retry_policy._trailing_streak(history, "stall") + 1
            self._queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
            self._log.warning("task_stall_handled", task_id=task.id, count=rounds)
            return

        if outcome == TaskOutcome.FAILURE:
            history = attempts.load_attempts(task_dir)
            rounds = retry_policy._trailing_streak(history, "failure") + 1
            note = f" Worker summary: {result.summary}" if result and result.summary else ""
            self._queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
            self._queue.comment(
                task.id,
                f"[fleet] failure {rounds} (rc={record.exit_code}). "
                f"Releasing for retry.{note}",
            )
            self._log.warning("task_failure_release", task_id=task.id, failures=rounds)
            return

        if outcome == TaskOutcome.PARTIAL:
            history = attempts.load_attempts(task_dir)
            rounds = retry_policy._trailing_streak(history, "partial") + 1
            self._queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
            self._queue.comment(
                task.id,
                f"[fleet] partial progress #{rounds}/{PARTIAL_MAX_ROUNDS}: {decision.reason}",
            )
            self._log.info("task_partial_release", task_id=task.id, count=rounds)
            return

        if outcome == TaskOutcome.SUCCESS:
            history = attempts.load_attempts(task_dir)
            rounds = retry_policy._trailing_streak(history, "noclose") + 1
            self._queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
            self._queue.comment(
                task.id,
                f"[fleet] success #{rounds}/{NOCLOSE_MAX_ROUNDS}: rc=0, "
                f"worker exited without RESULT.json. "
                f"At {NOCLOSE_MAX_ROUNDS} the task will be blocked for human review.",
            )
            self._log.warning("task_success_noclose", task_id=task.id, count=rounds)
            return

        if outcome == TaskOutcome.CONTEXT_PRESSURE:
            history = attempts.load_attempts(task_dir)
            rounds = retry_policy._trailing_streak(history, "context") + 1
            self._queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
            self._queue.comment(
                task.id,
                f"[fleet] context limit round {rounds}/{CONTEXT_MAX_ROUNDS}; "
                f"compaction + continue",
            )
            self._log.info("task_context_release", task_id=task.id, count=rounds)
            return

        # Anything else: plain release.
        self._queue.release(task.id, reason=decision.reason, wait_sec=wait_sec)
        self._log.info("task_released", task_id=task.id, **fleet_ctx)

    def _snapshot_attempt_artifacts(self, task: Task, task_dir: Path, n: int) -> None:
        """Copy this attempt's RESULT.json/HANDOFF.md into its attempts/<n>/
        folder and render SUMMARY.md, so the attempts timeline has a
        self-contained per-attempt record even after `artifacts/` moves on.
        """
        attempt_dir = attempts.attempt_dir(task_dir, n)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir = task_dir / "artifacts"

        result_src = artifacts_dir / "RESULT.json"
        if result_src.exists():
            try:
                (attempt_dir / "RESULT.json").write_bytes(result_src.read_bytes())
            except OSError as exc:
                self._log.warning(
                    "attempt_snapshot_failed", task_id=task.id, file="RESULT.json", error=str(exc)
                )

        handoff_src = artifacts_dir / "HANDOFF.md"
        if handoff_src.exists():
            try:
                (attempt_dir / "HANDOFF.md").write_bytes(handoff_src.read_bytes())
            except OSError as exc:
                self._log.warning(
                    "attempt_snapshot_failed", task_id=task.id, file="HANDOFF.md", error=str(exc)
                )

        workdir = _resolve_workdir(task, task_dir)

        try:
            write_summary(task_dir, n, workdir)
        except OSError as exc:
            self._log.warning("attempt_summary_failed", task_id=task.id, error=str(exc))

    def _handle_outcome(
        self, task: Task, outcome: TaskOutcomeRecord, attempt_n: int | None = None
    ) -> None:
        task_dir = self._task_dir_for(task)
        fleet_ctx = self._fleet_log_context()
        bead_status = self._bead_status(task.id)

        result = self._read_declared_result(task_dir)

        decision = self._maybe_handle_isolated_success(
            task, task_dir, outcome, bead_status, result
        )
        record = outcome
        if decision is None:
            if record.outcome == TaskOutcome.SUCCESS and bead_status == "blocked":
                record = TaskOutcomeRecord(
                    outcome=TaskOutcome.BLOCKED_BY_AGENT,
                    exit_code=record.exit_code,
                    reason="agent set task to blocked",
                )
            elif record.outcome == TaskOutcome.SUCCESS and result is not None:
                record = self._fold_declared_result(record, result)
            history = attempts.load_attempts(task_dir)
            decision = retry_policy.decide(record, history, bead_status, self.config)
            self._apply_decision(
                task, task_dir, record, decision, fleet_ctx, bead_status=bead_status, result=result
            )
        else:
            # Isolated-success path already produced a Decision; apply it so
            # queue state, comments, and the attempts.jsonl action all agree.
            self._apply_decision(
                task, task_dir, record, decision, fleet_ctx, bead_status=bead_status, result=result
            )

        try:
            attempts.record_end(
                task_dir,
                outcome=record.outcome.value,
                exit_code=record.exit_code,
                reason=record.reason,
                action=decision.action.value,
                n=attempt_n,
            )
        except OSError as exc:
            self._log.warning(
                "attempt_record_failed", task_id=task.id, error=str(exc)
            )
            return

        n = attempt_n or attempts.current_attempt_n(task_dir)
        if n > 0:
            self._snapshot_attempt_artifacts(task, task_dir, n)
