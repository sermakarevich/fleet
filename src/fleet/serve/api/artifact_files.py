"""Artifact file reads for the task artifact routes.

Called by serve/api/tasks_artifacts.py (and the templates route) via
`asyncio.to_thread` (the blocking-I/O rule in serve/api/__init__.py):
handlers never read the filesystem on the event-loop thread. Every helper
here is sync and returns plain data or a JSONResponse.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import JSONResponse

from fleet.serve.errors import not_found
from fleet.serve.state import AppState
from fleet.state.paths import task_dir as resolve_task_dir
from fleet.state.task_summary import read_declared_result


def read_artifact(path: Path) -> tuple[str, float, str]:
    """(content, mtime, resolved path) for one artifact file."""
    return (path.read_text(encoding="utf-8"), path.stat().st_mtime, str(path.resolve()))


def file_response(content: str, mtime: float, resolved: str) -> JSONResponse:
    """Artifact payload for already-read file content."""
    return JSONResponse({"content": content, "mtime": mtime, "path": resolved})


def list_output_names(outputs: Path) -> list[str]:
    """Deliverable file names under outputs/, [] when missing/unreadable."""
    if not outputs.is_dir():
        return []
    try:
        return sorted(p.name for p in outputs.iterdir() if p.is_file())
    except OSError:
        return []


def read_named_artifact(path: Path) -> tuple[str, float, str] | None:
    """(content, mtime, resolved) for a named artifact, None when missing."""
    if not path.exists():
        return None
    try:
        return read_artifact(path)
    except OSError:
        return None


def named_artifact(task_id: str, state: AppState, filename: str) -> JSONResponse:
    """Named artifact response for one task (RESEARCH.md, DESIGN.md, ...)."""
    task_path = resolve_task_dir(state.fleet_home, task_id) / "artifacts" / filename
    snapshot = read_named_artifact(task_path)
    if snapshot is None:
        raise not_found("artifact", filename)
    return file_response(*snapshot)


def read_children_md(digest_file: Path) -> str | None:
    """CHILDREN.md text, None when missing/unreadable."""
    if not digest_file.exists():
        return None
    try:
        return digest_file.read_text(encoding="utf-8")
    except OSError:
        return None


def children_payload(deps: list[dict], state: AppState, task_dir: Path) -> dict:
    """Children rows + CHILDREN.md for the epic children panel."""
    children = [_child_row(dep, state) for dep in deps if _has_id(dep)]
    children_md = read_children_md(task_dir / "artifacts" / "CHILDREN.md")
    return {"children": children, "children_md": children_md}


def _has_id(dep: object) -> bool:
    return isinstance(dep, dict) and bool(dep.get("id"))


def _child_row(dep: dict, state: AppState) -> dict:
    cid = str(dep["id"])
    declared = read_declared_result(resolve_task_dir(state.fleet_home, cid))
    return {
        "id": cid,
        "title": dep.get("title"),
        "status": dep.get("status"),
        "result_status": (declared or {}).get("status"),
        "result_summary": (declared or {}).get("summary"),
    }


def read_text_or_empty(path: Path) -> str:
    """Whole file text, "" when missing/unreadable."""
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_templates(templates_dir: Path) -> list[dict]:
    """Prompt template names + contents under the fleet home."""
    templates: list[dict] = []
    if not templates_dir.is_dir():
        return templates
    for f in sorted(templates_dir.glob("*.md")):
        try:
            templates.append({"name": f.stem, "content": f.read_text(encoding="utf-8")})
        except OSError:
            continue
    return templates
