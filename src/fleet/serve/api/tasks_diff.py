"""Task diff route: worktree-aware git diff (ADR 0017 U1)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from fleet.serve.api.models import DiffResponse
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.state import StateDep
from fleet.state.task_index import TaskIndex

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])

_DIFF_TIMEOUT_SEC = 10


async def _git_diff(cwd: str, base_ref: str | None) -> tuple[str, str]:
    """(diff, note) for `git -C <cwd> diff [base_ref]` with stderr captured."""
    args = ["git", "-C", cwd, "diff"]
    if base_ref:
        args.append(base_ref)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_DIFF_TIMEOUT_SEC)
    except TimeoutError:
        return "", "git timed out"
    except OSError as exc:
        return "", f"git failed: {exc}".splitlines()[0]
    if proc.returncode != 0:
        first = (stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        detail = first[0] if first else f"exit {proc.returncode}"
        return "", f"git failed: {detail}"
    return (stdout or b"").decode("utf-8", errors="replace"), ""


@router.get("/tasks/{task_id}/diff", response_model=DiffResponse)
async def get_task_diff(task_id: str, state: StateDep) -> JSONResponse:
    """git diff against the worktree base ref, else the task cwd (ADR 0017)."""
    raw = TaskIndex(state.fleet_home).read_raw(task_id) or {}
    worktree_path = raw.get("worktree_path")
    if worktree_path:
        if not Path(str(worktree_path)).is_dir():
            return JSONResponse({"diff": "", "note": "worktree removed"})
        diff, note = await _git_diff(str(worktree_path), raw.get("base_ref"))
        return JSONResponse({"diff": diff, "note": note})
    cwd = raw.get("cwd")
    if not cwd:
        return JSONResponse({"diff": "", "note": "no working directory"})
    diff, note = await _git_diff(str(cwd), None)
    return JSONResponse({"diff": diff, "note": note})
