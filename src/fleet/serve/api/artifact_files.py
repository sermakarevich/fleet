"""Artifact file reads for the task artifact bundle and detail routes.

Called by serve/api/tasks_artifacts.py (bundle) and tasks_detail.py
(children) via `asyncio.to_thread` (the blocking-I/O rule in
serve/api/__init__.py): handlers never read the filesystem on the
event-loop thread. Every helper here is sync and returns plain data.
"""

from __future__ import annotations

from pathlib import Path

from fleet.serve.state import AppState
from fleet.state.artifact_locator import locate
from fleet.state.events import EventScanCache, event_stats_cached
from fleet.state.paths import task_dir as resolve_task_dir
from fleet.state.task_summary import read_declared_result

_events_cache = EventScanCache()


def files_payload(task_path: Path) -> list[dict]:
    """Per-file read/edit/write counts from the event scan."""
    counts = event_stats_cached(task_path, _events_cache).files_touched
    return [
        {"path": path, "read": fc.read, "edit": fc.edit, "write": fc.write}
        for path, fc in sorted(counts.items())
    ]


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


#: Artifact doc truncation: content past this is cut, `truncated` says so.
ARTIFACT_DOC_LIMIT = 200_000

#: Worktree pointer keys read from task.json for the bundle (ADR 0017 U1).
_WORKTREE_KEYS = ("repo_root", "base_ref", "worktree_path")


def _doc_payload(name: str, path: Path) -> dict | None:
    """ArtifactDoc dict for one file, None when missing/unreadable."""
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8")
        mtime = path.stat().st_mtime
    except OSError:
        return None
    truncated = len(text) > ARTIFACT_DOC_LIMIT
    if truncated:
        text = text[:ARTIFACT_DOC_LIMIT]
    return {"name": name, "content": text, "mtime": mtime, "truncated": truncated}


def bundle_payload(task_dir: Path, raw_task_json: dict | None) -> dict:
    """One artifact bundle: result/state docs, outputs, docs, files, worktree."""
    fleet_home = task_dir.parent.parent
    task_id = task_dir.name
    result_path = locate(fleet_home, task_id, "result")
    result = _doc_payload(result_path.name, result_path)
    state_path = locate(fleet_home, task_id, "state")
    state = _doc_payload(state_path.name, state_path)

    outputs: list[dict] = []
    outputs_dir = task_dir / "outputs"
    try:
        names = sorted(p.name for p in outputs_dir.iterdir() if p.is_file())
    except OSError:
        names = []
    for name in names:
        if name == "outputs.json":
            continue
        try:
            st = (outputs_dir / name).stat()
        except OSError:
            continue
        outputs.append(
            {"name": name, "path": str((outputs_dir / name).resolve()), "size": st.st_size}
        )

    docs: list[dict] = []
    artifacts_dir = task_dir / "artifacts"
    try:
        doc_names = sorted(
            p.name
            for p in artifacts_dir.iterdir()
            if p.is_file() and p.suffix in (".md", ".json") and p.name != "RESULT.json"
        )
    except OSError:
        doc_names = []
    for name in doc_names:
        doc = _doc_payload(name, artifacts_dir / name)
        if doc is not None:
            docs.append(doc)

    raw = raw_task_json or {}
    worktree = None
    if any(key in raw for key in _WORKTREE_KEYS):
        wt_path = raw.get("worktree_path")
        worktree = {
            "repo_root": raw.get("repo_root"),
            "base_ref": raw.get("base_ref"),
            "worktree_path": wt_path,
            "exists": bool(wt_path) and Path(str(wt_path)).is_dir(),
        }
    return {
        "result": result,
        "state": state,
        "outputs": outputs,
        "docs": docs,
        "files": files_payload(task_dir),
        "worktree": worktree,
    }


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
