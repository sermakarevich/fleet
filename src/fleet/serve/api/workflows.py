"""Workflow REST routes: list, create, edit, delete, validate, import, export, run.

Thin handlers (ADR 0006 rule 3): parse the body, call `workflows.*`, format
the view. Every blocking call (store I/O, `bd`, the queue) runs in a sync
helper via `asyncio.to_thread`. Called by serve/app.py through ROUTERS; the
UI workflows tab reads these.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError

from fleet.beads.client import BdError
from fleet.beads.queue import Queue
from fleet.coders import get_coder
from fleet.core.errors import WorkflowInvalid, WorkflowNameTaken, WorkflowNotFound
from fleet.observability.process import service_status
from fleet.serve.api.models import (
    OkResponse,
    StartRunRequest,
    StartRunResponse,
    WorkflowExportResponse,
    WorkflowListResponse,
    WorkflowRequest,
    WorkflowRunListResponse,
    WorkflowRunView,
    WorkflowValidateResponse,
    WorkflowView,
)
from fleet.serve.auth import HTTP_AUTH
from fleet.serve.errors import (
    bad_gateway,
    conflict,
    not_found,
    parse_json_body,
    unprocessable,
)
from fleet.serve.state import StateDep
from fleet.state import task_actions
from fleet.workflows.model import (
    Defaults,
    RunStatus,
    Stage,
    Step,
    Trigger,
    Workflow,
    WorkflowInput,
    WorkflowRun,
    ensure_valid,
    new_id,
    step_state_of,
    validate,
)
from fleet.workflows.runs import cancel_run, refresh_run_with_tasks, start_run
from fleet.workflows.store import WorkflowStore
from fleet.workflows.yaml_io import from_yaml, to_yaml

router = APIRouter(prefix="/api", dependencies=[HTTP_AUTH])

_FETCH_LIMIT = 10000
_LIST_LIMIT_MAX = 200
_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _step_from_request(raw: Any) -> Step:
    """One Step dataclass from a validated request step."""
    needs = raw.needs if isinstance(raw.needs, list) else []
    return Step(
        name=raw.name,
        title=raw.title,
        description=raw.description or "",
        cwd=raw.cwd,
        coder=raw.coder,
        model=raw.model,
        priority=raw.priority,
        needs=tuple(str(item) for item in needs),
        isolation=raw.isolation,
    )


def _input_from_request(raw: Any) -> WorkflowInput:
    """One WorkflowInput dataclass from a validated request input."""
    return WorkflowInput(
        name=raw.name,
        description=raw.description or "",
        required=raw.required,
        default=raw.default,
    )


def _workflow_from_request(
    req: WorkflowRequest, *, workflow_id: str, created_at: str, now: datetime
) -> Workflow:
    """One Workflow dataclass from a validated request body."""
    return Workflow(
        id=workflow_id,
        name=req.name,
        description=req.description or "",
        defaults=Defaults(
            cwd=req.defaults.cwd,
            coder=req.defaults.coder,
            model=req.defaults.model,
            priority=req.defaults.priority,
            isolation=req.defaults.isolation,
        ),
        inputs=tuple(_input_from_request(item) for item in req.inputs),
        stages=tuple(
            Stage(name=stage.name, steps=tuple(_step_from_request(item) for item in stage.steps))
            for stage in req.stages
        ),
        created_at=created_at,
        updated_at=now.isoformat(),
    )


def _check_coders(workflow: Workflow) -> None:
    """Raise 422 naming the first unknown coder in defaults or any step."""
    names = [workflow.defaults.coder]
    names.extend(step.coder for stage in workflow.stages for step in stage.steps)
    for name in names:
        if name is None:
            continue
        try:
            get_coder(name)
        except ValueError as exc:
            raise unprocessable(f"coder: {exc}") from exc


def _check_cwds(workflow: Workflow) -> None:
    """Raise 422 naming the first cwd that is not an existing directory."""
    paths = [workflow.defaults.cwd]
    paths.extend(step.cwd for stage in workflow.stages for step in stage.steps)
    for cwd in paths:
        if cwd is not None and not Path(cwd).is_dir():
            raise unprocessable(f"cwd: not an existing directory: {cwd!r}")


def _validated(body: Any, *, workflow_id: str, created_at: str, now: datetime) -> Workflow:
    """Build a Workflow from a JSON body, raising 422 naming the bad field."""
    if not isinstance(body, dict):
        raise unprocessable("workflow body must be a JSON object")
    try:
        req = WorkflowRequest.model_validate(body)
    except ValidationError as exc:
        raise unprocessable(str(exc)) from exc
    if not req.name.strip():
        raise unprocessable("name: required and must not be empty")
    workflow = _workflow_from_request(req, workflow_id=workflow_id, created_at=created_at, now=now)
    try:
        ensure_valid(workflow)
    except WorkflowInvalid as exc:
        raise unprocessable("; ".join(exc.problems)) from exc
    _check_coders(workflow)
    _check_cwds(workflow)
    return workflow


def _run_view(
    run: WorkflowRun, *, store: WorkflowStore, titles: dict[str, str | None]
) -> dict[str, Any]:
    """One run with its step runs (titles null when the task is gone)."""
    steps = [
        {
            "step_name": item.step_name,
            "stage_index": item.stage_index,
            "task_id": item.task_id,
            "task_status": item.task_status,
            "state": step_state_of(item.task_status).value,
            "task_title": titles.get(item.task_id),
            "updated_at": item.updated_at,
            "outputs": dict(item.outputs),
            "warning": item.warning,
        }
        for item in store.step_runs(run.id)
    ]
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "workflow_name": run.spec.name,
        "n": run.n,
        "trigger": run.trigger.value,
        "schedule_id": run.schedule_id,
        "status": run.status.value,
        "reason": run.reason,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "inputs": dict(run.inputs),
        "steps": steps,
    }


def _refreshed_view(
    run: WorkflowRun, *, store: WorkflowStore, queue: Queue, now: datetime
) -> dict[str, Any]:
    """One run view; running runs refresh first (one bd call, titles reused)."""
    if run.status != RunStatus.running:
        return _run_view(run, store=store, titles={})
    refreshed, tasks = refresh_run_with_tasks(run, store=store, queue=queue, now=now)
    return _run_view(refreshed, store=store, titles={task.id: task.title for task in tasks})


def _workflow_view(
    workflow: Workflow, *, store: WorkflowStore, last_run: dict[str, Any] | None
) -> dict[str, Any]:
    """One saved workflow with counts and its latest run view."""
    data = workflow.to_dict()
    step_count = sum(len(stage.steps) for stage in workflow.stages)
    return {
        **data,
        "step_count": step_count,
        "stage_count": len(workflow.stages),
        "run_count": store.run_count(workflow.id),
        "last_run": last_run,
    }


def _with_last_run(
    workflow: Workflow, *, store: WorkflowStore, queue: Queue, now: datetime
) -> dict[str, Any]:
    """One workflow view with its latest run refreshed when still running."""
    last = store.last_run(workflow.id)
    view = _refreshed_view(last, store=store, queue=queue, now=now) if last is not None else None
    return _workflow_view(workflow, store=store, last_run=view)


def _list(store: WorkflowStore, queue: Queue, now: datetime) -> dict[str, Any]:
    """All workflows with counts and refreshed latest runs (runs in a thread)."""
    workflows = [_with_last_run(item, store=store, queue=queue, now=now) for item in store.list()]
    return {"workflows": workflows}


def _create(store: WorkflowStore, body: Any, now: datetime) -> dict[str, Any]:
    """Validate, save with a fresh id, and return the view (runs in a thread)."""
    moment = now.isoformat()
    workflow = _validated(body, workflow_id=new_id(), created_at=moment, now=now)
    try:
        store.save(workflow)
    except WorkflowNameTaken as exc:
        raise conflict(f"workflow name already taken: {exc.name}") from exc
    return _workflow_view(workflow, store=store, last_run=None)


def _get(
    store: WorkflowStore, queue: Queue, workflow_id: str, now: datetime
) -> dict[str, Any] | None:
    """One workflow view, or None when unknown (runs in a thread)."""
    workflow = store.get(workflow_id)
    if workflow is None:
        return None
    return _with_last_run(workflow, store=store, queue=queue, now=now)


def _update(
    store: WorkflowStore, queue: Queue, workflow_id: str, body: Any, now: datetime
) -> dict[str, Any] | None:
    """Validate and rewrite a workflow, keeping id/created_at (runs in a thread)."""
    existing = store.get(workflow_id)
    if existing is None:
        return None
    workflow = _validated(body, workflow_id=workflow_id, created_at=existing.created_at, now=now)
    try:
        store.save(workflow)
    except WorkflowNameTaken as exc:
        raise conflict(f"workflow name already taken: {exc.name}") from exc
    return _with_last_run(workflow, store=store, queue=queue, now=now)


def _delete(store: WorkflowStore, workflow_id: str) -> bool | None:
    """Remove a workflow; None when unknown, False when a run still runs."""
    if store.get(workflow_id) is None:
        return None
    for run in store.list_runs(workflow_id=workflow_id, limit=_FETCH_LIMIT):
        if run.status == RunStatus.running:
            return False
    return store.delete(workflow_id)


def _validate_body(body: Any) -> dict[str, Any]:
    """Structural plus coder/cwd problems; invalid content is valid=false."""
    if not isinstance(body, dict):
        return {"valid": False, "problems": ["body: must be a JSON object"]}
    try:
        req = WorkflowRequest.model_validate(body)
    except ValidationError as exc:
        return {"valid": False, "problems": [str(exc)]}
    problems = validate(
        _workflow_from_request(req, workflow_id="wf-validate", created_at="", now=datetime.now(UTC))
    )
    if not req.name.strip():
        problems.append("name: required and must not be empty")
    for name in [req.defaults.coder, *(step.coder for stage in req.stages for step in stage.steps)]:
        if name is None:
            continue
        try:
            get_coder(name)
        except ValueError as exc:
            problems.append(f"coder: {exc}")
    for cwd in [req.defaults.cwd, *(step.cwd for stage in req.stages for step in stage.steps)]:
        if cwd is not None and not Path(cwd).is_dir():
            problems.append(f"cwd: not an existing directory: {cwd!r}")
    return {"valid": not problems, "problems": problems}


def _import_workflow(
    store: WorkflowStore, queue: Queue, body: Any, now: datetime
) -> dict[str, Any]:
    """Parse YAML, assign ids, save new or replace; clashes raise 409."""
    payload = body if isinstance(body, dict) else {}
    text = payload.get("yaml", "")
    replace_id = payload.get("replace_id")
    if not isinstance(text, str) or not text.strip():
        raise unprocessable("yaml: required and must not be empty")
    if replace_id is not None and not isinstance(replace_id, str):
        raise unprocessable("replace_id: must be a string")
    try:
        parsed = from_yaml(text)
    except WorkflowInvalid as exc:
        raise unprocessable("; ".join(exc.problems)) from exc
    _check_coders(parsed)
    _check_cwds(parsed)
    moment = now.isoformat()
    if replace_id:
        existing = store.get(replace_id)
        if existing is None:
            raise not_found("workflow", replace_id)
        clash = store.get_by_name(parsed.name)
        if clash is not None and clash.id != replace_id:
            raise conflict(f"workflow name already taken: {parsed.name}")
        workflow = Workflow(
            id=replace_id,
            name=parsed.name,
            description=parsed.description,
            defaults=parsed.defaults,
            inputs=parsed.inputs,
            stages=parsed.stages,
            created_at=existing.created_at,
            updated_at=moment,
        )
    else:
        if store.get_by_name(parsed.name) is not None:
            raise conflict(f"workflow name already taken: {parsed.name}")
        workflow = Workflow(
            id=parsed.id or new_id(),
            name=parsed.name,
            description=parsed.description,
            defaults=parsed.defaults,
            inputs=parsed.inputs,
            stages=parsed.stages,
            created_at=moment,
            updated_at=moment,
        )
    try:
        store.save(workflow)
    except WorkflowNameTaken as exc:
        raise conflict(f"workflow name already taken: {exc.name}") from exc
    return _with_last_run(workflow, store=store, queue=queue, now=now)


def _export(store: WorkflowStore, workflow_id: str) -> tuple[str, str] | None:
    """One workflow's (name, YAML), or None when unknown (runs in a thread)."""
    workflow = store.get(workflow_id)
    if workflow is None:
        return None
    return workflow.name, to_yaml(workflow)


def _safe_filename(name: str) -> str:
    """Filesystem-safe download name for the export attachment."""
    safe = _FILENAME_SAFE_RE.sub("_", name.strip()).strip("._")
    return safe or "workflow"


def _start_run(
    store: WorkflowStore,
    queue: Queue,
    workflow_id: str,
    now: datetime,
    body: StartRunRequest | None,
) -> dict[str, Any] | None:
    """Open every step's bead for one manual run; None when unknown."""
    workflow = store.get(workflow_id)
    if workflow is None:
        return None
    given = body.inputs if body is not None else {}
    try:
        run = start_run(
            workflow, store=store, queue=queue, now=now, trigger=Trigger.manual, inputs=given
        )
    except WorkflowInvalid as exc:
        raise unprocessable("; ".join(exc.problems)) from exc
    except BdError as exc:
        raise bad_gateway(str(exc) or "queue failed") from exc
    refreshed, tasks = refresh_run_with_tasks(run, store=store, queue=queue, now=now)
    return {
        "run": _run_view(refreshed, store=store, titles={task.id: task.title for task in tasks})
    }


def _list_runs(
    store: WorkflowStore,
    queue: Queue,
    *,
    workflow_id: str | None,
    status: str | None,
    limit: int,
    offset: int,
    now: datetime,
) -> dict[str, Any]:
    """Paged run views, optionally filtered; running ones refresh (in a thread)."""
    wanted: RunStatus | None = None
    if status is not None:
        try:
            wanted = RunStatus(status)
        except ValueError:
            raise unprocessable(f"status: unknown run status {status!r}") from None
    candidates = store.list_runs(workflow_id=workflow_id, limit=_FETCH_LIMIT)
    if wanted is not None:
        candidates = [run for run in candidates if run.status == wanted]
    total = len(candidates)
    views = [
        _refreshed_view(run, store=store, queue=queue, now=now)
        for run in candidates[offset : offset + limit]
    ]
    return {"runs": views, "total": total}


def _run_detail(
    store: WorkflowStore, queue: Queue, run_id: str, now: datetime
) -> dict[str, Any] | None:
    """One run view with task titles from a single bd call (runs in a thread)."""
    run = store.get_run(run_id)
    if run is None:
        return None
    if run.status == RunStatus.running:
        return _refreshed_view(run, store=store, queue=queue, now=now)
    try:
        tasks = queue.list_by_metadata("fleet_workflow_run", run.id)
    except BdError:
        tasks = []
    return _run_view(run, store=store, titles={task.id: task.title for task in tasks})


def _cancel_run(
    store: WorkflowStore,
    queue: Queue,
    fleet_home: Path,
    run_id: str,
    now: datetime,
    supervisor_running: bool,
) -> dict[str, Any] | None:
    """Cancel one run and return its view with fresh titles (runs in a thread)."""
    run = store.get_run(run_id)
    if run is None:
        return None
    try:
        finished = cancel_run(
            run, store=store, queue=queue, now=now, supervisor_running=supervisor_running
        )
    except BdError as exc:
        raise bad_gateway(str(exc) or "queue failed") from exc
    except task_actions.TaskNotFound as exc:
        raise unprocessable(str(exc)) from exc
    try:
        tasks = queue.list_by_metadata("fleet_workflow_run", finished.id)
    except BdError:
        tasks = []
    return _run_view(finished, store=store, titles={task.id: task.title for task in tasks})


def _reraise_missing(exc: WorkflowNotFound) -> None:
    """Map a stray WorkflowNotFound to the one 404 shape."""
    raise not_found("workflow", exc.workflow_id) from exc


@router.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(state: StateDep) -> JSONResponse:
    """Every workflow with counts and its refreshed latest run."""
    try:
        payload = await asyncio.to_thread(
            _list, state.workflow_store, state.queue, datetime.now(UTC)
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    return JSONResponse(payload)


@router.post("/workflows", response_model=WorkflowView)
async def create_workflow(request: Request, state: StateDep) -> JSONResponse:
    """Validate and save a workflow; 201 with the view."""
    body = await parse_json_body(request)
    try:
        payload = await asyncio.to_thread(_create, state.workflow_store, body, datetime.now(UTC))
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    return JSONResponse(payload, status_code=201)


@router.post("/workflows/validate", response_model=WorkflowValidateResponse)
async def validate_workflow(request: Request) -> JSONResponse:
    """Check a workflow body; invalid content is valid=false, never 4xx."""
    return JSONResponse(_validate_body(await parse_json_body(request)))


@router.post("/workflows/import", response_model=WorkflowView)
async def import_workflow(request: Request, state: StateDep) -> JSONResponse:
    """Import YAML as a workflow (or replace one); 201 with the view."""
    body = await parse_json_body(request)
    try:
        payload = await asyncio.to_thread(
            _import_workflow, state.workflow_store, state.queue, body, datetime.now(UTC)
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    return JSONResponse(payload, status_code=201)


@router.get("/workflows/{workflow_id}", response_model=WorkflowView)
async def get_workflow(workflow_id: str, state: StateDep) -> JSONResponse:
    """One workflow with counts and its refreshed latest run."""
    try:
        payload = await asyncio.to_thread(
            _get, state.workflow_store, state.queue, workflow_id, datetime.now(UTC)
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    if payload is None:
        raise not_found("workflow", workflow_id)
    return JSONResponse(payload)


@router.put("/workflows/{workflow_id}", response_model=WorkflowView)
async def update_workflow(workflow_id: str, request: Request, state: StateDep) -> JSONResponse:
    """Validate and rewrite a workflow, keeping id and created_at."""
    body = await parse_json_body(request)
    try:
        payload = await asyncio.to_thread(
            _update, state.workflow_store, state.queue, workflow_id, body, datetime.now(UTC)
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    if payload is None:
        raise not_found("workflow", workflow_id)
    return JSONResponse(payload)


@router.delete("/workflows/{workflow_id}", response_model=OkResponse)
async def delete_workflow(workflow_id: str, state: StateDep) -> JSONResponse:
    """Remove a workflow; 409 while one of its runs still runs."""
    try:
        removed = await asyncio.to_thread(_delete, state.workflow_store, workflow_id)
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    if removed is None:
        raise not_found("workflow", workflow_id)
    if removed is False:
        raise conflict(f"workflow {workflow_id} has a run still running")
    return JSONResponse({"ok": True})


@router.get("/workflows/{workflow_id}/export", response_model=WorkflowExportResponse)
async def export_workflow(
    workflow_id: str, state: StateDep, format: str = "yaml"
) -> JSONResponse | PlainTextResponse:
    """Export one workflow as YAML (or ?format=text for a direct download)."""
    if format not in ("yaml", "text"):
        raise unprocessable(f"format: expected 'yaml' or 'text', got {format!r}")
    try:
        found = await asyncio.to_thread(_export, state.workflow_store, workflow_id)
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    if found is None:
        raise not_found("workflow", workflow_id)
    name, text = found
    if format == "text":
        filename = f"{_safe_filename(name)}.yaml"
        return PlainTextResponse(
            text, headers={"content-disposition": f"attachment; filename={filename}"}
        )
    return JSONResponse({"yaml": text})


@router.post("/workflows/{workflow_id}/run", response_model=StartRunResponse)
async def run_workflow(
    workflow_id: str,
    state: StateDep,
    body: Annotated[StartRunRequest | None, Body()] = None,
) -> JSONResponse:
    """Start one manual run now and return it with its step runs."""
    try:
        payload = await asyncio.to_thread(
            _start_run, state.workflow_store, state.queue, workflow_id, datetime.now(UTC), body
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    if payload is None:
        raise not_found("workflow", workflow_id)
    return JSONResponse(payload, status_code=201)


@router.get("/workflows/{workflow_id}/runs", response_model=WorkflowRunListResponse)
async def list_workflow_runs(
    workflow_id: str,
    state: StateDep,
    limit: int = Query(default=50, ge=1, le=_LIST_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """Past runs of one workflow, newest first, running ones refreshed."""
    try:
        known = await asyncio.to_thread(state.workflow_store.get, workflow_id)
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    if known is None:
        raise not_found("workflow", workflow_id)
    try:
        payload = await asyncio.to_thread(
            _list_runs,
            state.workflow_store,
            state.queue,
            workflow_id=workflow_id,
            status=None,
            limit=limit,
            offset=offset,
            now=datetime.now(UTC),
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    return JSONResponse(payload)


@router.get("/workflow-runs", response_model=WorkflowRunListResponse)
async def list_all_workflow_runs(
    state: StateDep,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=_LIST_LIMIT_MAX),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """Every run across workflows, newest first, running ones refreshed."""
    try:
        payload = await asyncio.to_thread(
            _list_runs,
            state.workflow_store,
            state.queue,
            workflow_id=None,
            status=status,
            limit=limit,
            offset=offset,
            now=datetime.now(UTC),
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    return JSONResponse(payload)


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunView)
async def get_workflow_run(run_id: str, state: StateDep) -> JSONResponse:
    """One run with its step runs and task titles."""
    try:
        payload = await asyncio.to_thread(
            _run_detail, state.workflow_store, state.queue, run_id, datetime.now(UTC)
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    if payload is None:
        raise not_found("workflow run", run_id)
    return JSONResponse(payload)


@router.post("/workflow-runs/{run_id}/cancel", response_model=WorkflowRunView)
async def cancel_workflow_run(run_id: str, state: StateDep) -> JSONResponse:
    """Cancel one run (close waiting beads, kill running ones) and return it."""
    running = service_status("supervisor", state.fleet_home).alive
    try:
        payload = await asyncio.to_thread(
            _cancel_run,
            state.workflow_store,
            state.queue,
            state.fleet_home,
            run_id,
            datetime.now(UTC),
            running,
        )
    except WorkflowNotFound as exc:
        _reraise_missing(exc)
    if payload is None:
        raise not_found("workflow run", run_id)
    return JSONResponse(payload)
