from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fleet.core.limits import CLAIM_POLL_INTERVAL_SEC
from fleet.state.paths import tasks_root as _tasks_root
from fleet.state.validation_marker import clear_needs_validation, needs_validation

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


def read_isolation_info(task_dir: Path) -> dict | None:
    """Read repo_root/base_ref/worktree_path from task.json, or None.

    Falls back to the legacy `.worktree` marker for old task dirs.
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
                return {
                    "repo_root": meta.get("repo_root") if isinstance(meta, dict) else "",
                    "base_ref": (meta.get("base_ref") if isinstance(meta, dict) else None)
                    or "main",
                    "worktree_path": text,
                }
    except OSError:
        pass
    return None


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
                running = running_by_coder(self.in_flight_tasks.values(), self.config.coder)
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
                try:
                    self._spawn_worker(task)
                except Exception as exc:  # noqa: BLE001
                    # A bug between claim and spawn (half-edited coder code,
                    # bad config attribute) must not kill this loop: the task
                    # would stay in_progress forever and nothing else would
                    # ever be claimed again. Hand the bead back and carry on.
                    self._log.exception("spawn_failed", task_id=task.id, error=str(exc))
                    try:
                        await asyncio.to_thread(
                            self._queue.release,
                            task.id,
                            reason=f"spawn failed: {exc}",
                            wait_sec=60,
                        )
                    except Exception:  # noqa: BLE001
                        self._log.exception("spawn_failed_release", task_id=task.id)

            await self._run_pending_validations()

    def _finish_validation(self, task_dir: Path, task_id: str) -> None:
        """Clear validation state and drop isolation info after a terminal merge."""
        clear_needs_validation(task_dir)
        (task_dir / ".worktree").unlink(missing_ok=True)
        try:
            self._queue.clear_isolation_info(task_id)
        except AttributeError:
            pass
        except Exception:
            pass

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
            await self._validate_one(task_dir, task_id)
            return  # ONE per tick

    async def _validate_one(self, task_dir: Path, task_id: str) -> None:
        """Merge one validated worktree into its base ref, generically."""
        info = read_isolation_info(task_dir)
        if info is None or not info.get("repo_root"):
            await asyncio.to_thread(
                self._queue.set_blocked,
                task_id,
                "validation failed: missing isolation info; merge manually",
            )
            self._log.warning("task.validation_no_info", task_id=task_id)
            clear_needs_validation(task_dir)
            return
        repo_root = Path(info["repo_root"])
        base_ref = info.get("base_ref") or "main"
        wt_path = Path(info["worktree_path"])

        if not repo_root.is_dir():
            await asyncio.to_thread(
                self._queue.set_blocked,
                task_id,
                f"validation failed: repo_root gone ({repo_root}); merge manually",
            )
            clear_needs_validation(task_dir)
            return

        # Never touch a dirty base checkout.
        if worktree.is_repo_dirty(repo_root):
            await asyncio.to_thread(
                self._queue.set_blocked, task_id, "base repo dirty; merge manually"
            )
            self._log.warning("task.validation_dirty_base", task_id=task_id)
            clear_needs_validation(task_dir)
            return

        # Worktree must still be clean and ahead of base.
        if not wt_path.is_dir() or not worktree.is_committed_clean(
            wt_path, base_ref=base_ref
        ):
            await asyncio.to_thread(
                self._queue.set_blocked,
                task_id,
                f"validation failed: worktree not clean/ahead of {base_ref}; merge manually",
            )
            self._log.warning("task.validation_not_clean", task_id=task_id)
            worktree.cleanup_worktree(
                repo_root, task_id, wt_path, fleet_home=self._project_root
            )
            self._finish_validation(task_dir, task_id)
            return

        result = worktree.merge_to_base(repo_root, task_id, base_ref=base_ref)
        if not result.ok:
            reason = (
                f"merge conflict into {base_ref}; resolve on branch fleet/{task_id} then close"
                if result.conflict
                else f"validation merge failed: {result.message}"
            )
            await asyncio.to_thread(self._queue.set_blocked, task_id, reason)
            self._log.warning(
                "task.validation_failed",
                task_id=task_id,
                conflict=result.conflict,
            )
            worktree.cleanup_worktree(
                repo_root, task_id, wt_path, fleet_home=self._project_root
            )
            self._finish_validation(task_dir, task_id)
            return

        # Generic post-merge step (fleet's own repo sets this to `make ui-build`).
        post_cmd = getattr(self.config, "post_merge_command", "") or ""
        if post_cmd.strip():
            ok, tail = await asyncio.to_thread(
                worktree.run_post_merge_command, post_cmd, repo_root
            )
            if not ok:
                await asyncio.to_thread(
                    self._queue.set_blocked,
                    task_id,
                    f"post-merge command failed:\n{tail}",
                )
                self._log.warning("task.post_merge_failed", task_id=task_id)
                worktree.cleanup_worktree(
                    repo_root, task_id, wt_path, fleet_home=self._project_root
                )
                self._finish_validation(task_dir, task_id)
                return

        await asyncio.to_thread(
            self._queue.close,
            task_id,
            reason=f"validated: merged fleet/{task_id} into {base_ref}",
        )
        self._log.info("task.validated", task_id=task_id)
        worktree.cleanup_worktree(
            repo_root, task_id, wt_path, fleet_home=self._project_root
        )
        try:
            await asyncio.to_thread(worktree.delete_branch, repo_root, task_id)
        except Exception:
            pass
        self._finish_validation(task_dir, task_id)
