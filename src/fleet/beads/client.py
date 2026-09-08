"""The one client for the `bd` CLI: subprocess invocation and envelope unwrap."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class BeadsError(RuntimeError):
    pass


def run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run `bd <args>` with cwd=cwd. Raises BeadsError on non-zero rc unless check=False."""
    full_env = {**os.environ, **env} if env else None
    try:
        result = subprocess.run(
            ["bd", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=full_env,
        )
    except FileNotFoundError as exc:
        raise BeadsError("bd executable not found") from exc
    if check and result.returncode != 0:
        raise BeadsError(result.stderr.strip())
    return result


def _unwrap(data: Any) -> Any:
    """Unwrap the optional {"data": ...} envelope bd emits with --json."""
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def run_json(
    args: list[str], *, cwd: Path, env: dict[str, str] | None = None
) -> Any:
    """Run `bd <args> --json` and return the unwrapped payload (None if empty)."""
    full_args = list(args)
    if "--json" not in full_args:
        full_args.append("--json")
    result = run(full_args, cwd=cwd, env=env)
    if not result.stdout.strip():
        return None
    return _unwrap(json.loads(result.stdout))


def list_all(cwd: Path) -> list[dict]:
    data = run_json(["list", "--all", "--limit", "0"], cwd=cwd)
    return data if isinstance(data, list) else []


def show(task_id: str, cwd: Path) -> dict | None:
    data = run_json(["show", task_id], cwd=cwd)
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) else None


def update(task_id: str, cwd: Path, *, actor: str | None = None, **fields: Any) -> None:
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
    run(args, cwd=cwd, env=env)


def comment(task_id: str, text: str, cwd: Path) -> None:
    run(["comment", task_id, text], cwd=cwd)


# Dependency relations that make a bead an epic's *child*: the epic is
# blocked until these close. `bd show <epic>` lists them under
# "dependencies" (same query as `show()` above). When bd reports a relation
# type, only these two count; when it doesn't, every dependency counts.
_CHILD_RELATIONS = frozenset({"blocks", "depends_on"})


def children_of(epic_id: str, cwd: Path) -> list[dict]:
    """Return the epic's child beads as [{id, status, title, ...}].

    A child is one of the epic's dependencies (``bd dep add <epic> <child>``
    means the epic waits for the child). Each entry carries whatever `bd
    show` reported (status, title, close_reason when present); entries
    without an id are skipped.
    """
    body = show(epic_id, cwd)
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
