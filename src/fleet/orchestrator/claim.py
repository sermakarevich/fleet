from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime

from fleet.core.limits import CLAIM_POLL_INTERVAL_SEC
from fleet.state.counters import clear_needs_validation, needs_validation
from fleet.state.paths import tasks_root as _tasks_root

from . import worktree


def parse_overrides(raw: str) -> dict[str, int]:
    """Parse "claude:2,opencode:4" into {"claude": 2, "opencode": 4}.

    Blank or malformed entries and non-positive counts are ignored.
    """
    result: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, _, value = part.partition(":")
        name = name.strip()
        try:
            count = int(value.strip())
        except ValueError:
            continue
        if name and count > 0:
            result[name] = count
    return result


def cap_for_coder(coder: str, max_concurrent: int, overrides: str) -> int:
    """Concurrency cap for `coder`: its override if listed, else `max_concurrent`."""
    return parse_overrides(overrides).get(coder, max_concurrent)


def running_by_coder(tasks, default_coder: str) -> dict[str, int]:
    """Count how many of `tasks` run under each coder.

    `tasks` is any iterable of objects with a `.coder` attribute (None means
    the task uses the default coder).
    """
    counts: dict[str, int] = {}
    for task in tasks:
        coder = getattr(task, "coder", None) or default_coder
        counts[coder] = counts.get(coder, 0) + 1
    return counts


class ClaimMixin:
    async def _claim_and_spawn_loop(self) -> None:
        while not self._shutting_down:
            await asyncio.sleep(CLAIM_POLL_INTERVAL_SEC)
            if self._shutting_down:
                break

            now = datetime.now(tz=UTC)
            if self._paused_until is not None:
                if now < self._paused_until:
                    continue
                self._paused_until = None

            if (self._project_root / ".pause").exists():
                continue

            def _can_claim(coder: str | None) -> bool:
                running = running_by_coder(
                    self.in_flight_tasks.values(), self.config.coder
                )
                effective = coder or self.config.coder
                cap = cap_for_coder(
                    effective,
                    self.config.max_concurrent,
                    self.config.max_concurrent_overrides,
                )
                return running.get(effective, 0) < cap

            # bd is a subprocess; run it in a worker thread
            # so the event loop keeps tailing runner output.
            task = await asyncio.to_thread(
                self._queue.claim_next, "supervisor", can_claim=_can_claim
            )
            if task is not None:
                if task.id in self.in_flight:
                    # The task was flipped back to claimable externally
                    # (UI unblock, `bd update`) while our runner is still
                    # alive. Spawning again would orphan the live runner
                    # and put two agents on the same working tree.
                    self._log.warning(
                        "task_already_in_flight",
                        task_id=task.id,
                        in_flight=len(self.in_flight),
                    )
                    continue
                self._log.info(
                    "task_claimed",
                    task_id=task.id,
                    title=task.title[:80],
                    in_flight=len(self.in_flight) + 1,
                    cap=self.config.max_concurrent,
                    usage_pct=self.rate_gauge.current_pct(),
                )
                self._spawn_runner(task)

            await self._run_pending_validations()

    async def _run_pending_validations(self) -> None:
        tasks_root = _tasks_root(self._project_root)
        if not tasks_root.exists():
            return
        for task_dir in sorted(tasks_root.iterdir()):
            task_id = task_dir.name
            if task_id in self.in_flight:
                continue
            if not needs_validation(task_dir):
                continue
            result = worktree.merge_to_base(
                self._project_root, task_id, base_ref="main"
            )
            if result.ok:
                await asyncio.to_thread(
                    self._queue.close,
                    task_id,
                    reason=f"validated: merged fleet/{task_id} into main",
                )
                self._log.info("task.validated", task_id=task_id)

                # the merge just landed on main; rebuild the UI only if UI files changed
                diff = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self._project_root),
                        "diff",
                        "--name-only",
                        "HEAD~1",
                        "HEAD",
                    ],
                    capture_output=True,
                    text=True,
                )
                if any(
                    line.startswith("src/fleet/ui/")
                    for line in diff.stdout.splitlines()
                ):
                    proc = await asyncio.create_subprocess_exec(
                        "make",
                        "ui-build",
                        cwd=str(self._project_root),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    rc = await proc.wait()
                    if rc == 0:
                        self._log.info("ui.rebuilt", task_id=task_id)
                    else:
                        self._log.error("ui.rebuild_failed", task_id=task_id)
            else:
                reason = (
                    f"merge conflict into main; resolve on branch fleet/{task_id} then close"
                    if result.conflict
                    else f"validation merge failed: {result.message}"
                )
                await asyncio.to_thread(self._queue.set_blocked, task_id, reason)
                self._log.warning(
                    "task.validation_failed",
                    task_id=task_id,
                    conflict=result.conflict,
                )
            worktree.remove_worktree(self._project_root, task_id)
            clear_needs_validation(task_dir)
            (task_dir / ".worktree").unlink(missing_ok=True)
            return  # ONE per tick
