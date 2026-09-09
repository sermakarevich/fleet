"""The one client for the `bd` CLI: subprocess invocation and envelope unwrap.

Called by ``beads/queue.py`` (through :class:`BdClient`), ``beads/cache.py``,
``cli/tasks.py`` and ``cli/beads.py``. Every call carries a timeout so a hung
``bd`` raises :class:`BdError` instead of hanging the supervisor.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fleet.core.limits import BD_TIMEOUT_SEC


class BdError(RuntimeError):
    """A failed `bd` call: message plus the stderr and return code behind it."""

    def __init__(
        self,
        message: str,
        *,
        stderr: str = "",
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


def run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
    timeout: int = BD_TIMEOUT_SEC,
) -> subprocess.CompletedProcess:
    """Run `bd <args>` with cwd=cwd. Raises BdError on non-zero rc unless check=False."""
    full_env = {**os.environ, **env} if env else None
    try:
        result = subprocess.run(
            ["bd", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=full_env,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BdError("bd executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise BdError(
            f"bd {' '.join(args)} timed out after {timeout}s",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
        ) from exc
    if check and result.returncode != 0:
        message = result.stderr.strip()
        raise BdError(message, stderr=message, returncode=result.returncode)
    return result


class BdClient:
    """Per-repo `bd` runner; owns the timeout, the JSON envelope and the actor.

    ``beads/queue.py`` holds one of these and makes no other subprocess calls.
    """

    def __init__(self, repo_root: Path, *, timeout: int = BD_TIMEOUT_SEC) -> None:
        self.repo_root = repo_root
        self.timeout = timeout

    def run(
        self,
        argv: list[str],
        *,
        timeout: int | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
        actor: str | None = None,
    ) -> subprocess.CompletedProcess:
        """Run `bd <argv>`; BEADS_ACTOR is set when *actor* is given."""
        if actor is not None:
            env = {**(env or {}), "BEADS_ACTOR": actor}
        return run(
            argv,
            cwd=self.repo_root,
            check=check,
            env=env,
            timeout=self.timeout if timeout is None else timeout,
        )

    def run_json(
        self,
        argv: list[str],
        *,
        timeout: int | None = None,
        actor: str | None = None,
    ) -> Any:
        """Run `bd <argv> --json` and return the unwrapped payload (None if empty)."""
        full_args = list(argv)
        if "--json" not in full_args:
            full_args.append("--json")
        result = self.run(
            full_args,
            env={"BD_JSON_ENVELOPE": "1"},
            actor=actor,
            timeout=self.timeout if timeout is None else timeout,
        )
        if not result.stdout.strip():
            return None
        return _unwrap(json.loads(result.stdout))


def _unwrap(data: Any) -> Any:
    """Unwrap the optional {"data": ...} envelope bd emits with --json."""
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def run_json(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = BD_TIMEOUT_SEC,
) -> Any:
    """Run `bd <args> --json` and return the unwrapped payload (None if empty)."""
    full_args = list(args)
    if "--json" not in full_args:
        full_args.append("--json")
    result = run(full_args, cwd=cwd, env=env, timeout=timeout)
    if not result.stdout.strip():
        return None
    return _unwrap(json.loads(result.stdout))


def list_all(cwd: Path, *, timeout: int = BD_TIMEOUT_SEC) -> list[dict]:
    data = run_json(["list", "--all", "--limit", "0"], cwd=cwd, timeout=timeout)
    return data if isinstance(data, list) else []


def show(task_id: str, cwd: Path, *, timeout: int = BD_TIMEOUT_SEC) -> dict | None:
    data = run_json(["show", task_id], cwd=cwd, timeout=timeout)
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) else None


def update_bead(
    task_id: str,
    cwd: Path,
    *,
    actor: str | None = None,
    timeout: int = BD_TIMEOUT_SEC,
    **fields: Any,
) -> None:
    """Run `bd update <task_id> --<field> <value> ...`. Bool fields become bare flags."""
    args = ["update", task_id]
    for key, value in fields.items():
        if value is None:
            continue
        flag = "--" + key.replace("_", "-")
        if isinstance(value, bool):
            if value:
                args.append(flag)
        else:
            args += [flag, str(value)]
    env = {"BEADS_ACTOR": actor} if actor is not None else None
    run(args, cwd=cwd, env=env, timeout=timeout)


def comment(task_id: str, text: str, cwd: Path, *, timeout: int = BD_TIMEOUT_SEC) -> None:
    run(["comment", task_id, text], cwd=cwd, timeout=timeout)


# Dependency relations that make a bead an epic's *child*: the epic is
# blocked until these close. `bd show <epic>` lists them under
# "dependencies" (same query as `show()` above). When bd reports a relation
# type, only these two count; when it doesn't, every dependency counts.
_CHILD_RELATIONS = frozenset({"blocks", "depends_on"})


def children_of(epic_id: str, cwd: Path, *, timeout: int = BD_TIMEOUT_SEC) -> list[dict]:
    """Return the epic's child beads as [{id, status, title, ...}].

    A child is one of the epic's dependencies (``bd dep add <epic> <child>``
    means the epic waits for the child). Each entry carries whatever `bd
    show` reported (status, title, close_reason when present); entries
    without an id are skipped.
    """
    body = show(epic_id, cwd, timeout=timeout)
    if not isinstance(body, dict):
        return []
    deps = body.get("dependencies") or []
    children: list[dict] = []
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        dep_id = dep.get("id")
        if not dep_id:
            continue
        relation = dep.get("dependency_type") or dep.get("type")
        if relation is not None and relation not in _CHILD_RELATIONS:
            continue
        children.append(dep)
    return children
