"""YAML import and export for workflows: one file per workflow.

Called by the CLI, the serve API, and the UI upload/download buttons —
all three share this code path. Export writes the ADR 0008 shape (no ids
or timestamps unless asked); import validates the document and returns a
Workflow with empty id/timestamps for the caller to assign.
"""

from __future__ import annotations

from typing import Any

import yaml

from fleet.core.errors import WorkflowInvalid
from fleet.workflows.model import Defaults, Stage, Step, Workflow, ensure_valid

_YAML_VERSION = 1

_TOP_LEVEL_KEYS = frozenset(
    {
        "fleet_workflow",
        "id",
        "name",
        "description",
        "defaults",
        "stages",
        "created_at",
        "updated_at",
    }
)


def to_yaml(workflow: Workflow, *, with_ids: bool = False) -> str:
    """Render a workflow in the ADR 0008 file shape (block style, fixed order)."""
    doc: dict[str, Any] = {"fleet_workflow": _YAML_VERSION}
    if with_ids:
        doc["id"] = workflow.id
    doc["name"] = workflow.name
    doc["description"] = workflow.description
    doc["defaults"] = {
        "cwd": workflow.defaults.cwd,
        "coder": workflow.defaults.coder,
        "model": workflow.defaults.model,
        "priority": workflow.defaults.priority,
    }
    doc["stages"] = [_stage_to_yaml(stage) for stage in workflow.stages]
    if with_ids:
        doc["created_at"] = workflow.created_at
        doc["updated_at"] = workflow.updated_at
    return yaml.safe_dump(doc, sort_keys=False)


def _stage_to_yaml(stage: Stage) -> dict[str, Any]:
    """Render one stage as a YAML mapping."""
    return {"name": stage.name, "steps": [_step_to_yaml(step) for step in stage.steps]}


def _step_to_yaml(step: Step) -> dict[str, Any]:
    """Render one step, omitting optional fields the step leaves empty."""
    doc: dict[str, Any] = {"name": step.name, "title": step.title}
    doc["description"] = step.description
    if step.cwd is not None:
        doc["cwd"] = step.cwd
    if step.coder is not None:
        doc["coder"] = step.coder
    if step.model is not None:
        doc["model"] = step.model
    if step.priority is not None:
        doc["priority"] = step.priority
    if step.needs:
        doc["needs"] = list(step.needs)
    return doc


def from_yaml(text: str) -> Workflow:
    """Parse and validate one workflow document; ids stay empty for the caller."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WorkflowInvalid([f"yaml: cannot parse ({exc})"]) from None
    return _workflow_from_data(data)


def _workflow_from_data(data: Any) -> Workflow:
    """Validate the document shape, then the stage/needs rules."""
    if not isinstance(data, dict):
        raise WorkflowInvalid(["document: must be a mapping"])
    unknown = sorted(set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise WorkflowInvalid([f"{key}: unknown top-level key" for key in unknown])
    if data.get("fleet_workflow") != _YAML_VERSION:
        raise WorkflowInvalid(
            [f"fleet_workflow: expected {_YAML_VERSION}, got {data.get('fleet_workflow')!r}"]
        )
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise WorkflowInvalid(["name: required and must not be empty"])
    stages_raw = data.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise WorkflowInvalid(["stages: required and must not be empty"])
    description = data.get("description", "")
    if not isinstance(description, str):
        raise WorkflowInvalid(["description: must be a string"])
    workflow = Workflow(
        id=_optional_str(data, "id"),
        name=name,
        description=description,
        defaults=_defaults_from_data(data.get("defaults")),
        stages=tuple(_stage_from_data(item) for item in stages_raw),
        created_at=_optional_str(data, "created_at"),
        updated_at=_optional_str(data, "updated_at"),
    )
    return ensure_valid(workflow)


def _optional_str(data: dict[str, Any], key: str) -> str:
    """Read an optional string field, rejecting non-string values."""
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WorkflowInvalid([f"{key}: must be a string"])
    return value


def _defaults_from_data(data: Any) -> Defaults:
    """Parse the defaults mapping (absent means plain defaults)."""
    if data is None:
        return Defaults()
    if not isinstance(data, dict):
        raise WorkflowInvalid(["defaults: must be a mapping"])
    for key in ("cwd", "coder", "model"):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise WorkflowInvalid([f"defaults.{key}: must be a string"])
    priority = data.get("priority", 2)
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise WorkflowInvalid(["defaults.priority: must be an integer"])
    return Defaults(
        cwd=data.get("cwd"),
        coder=data.get("coder"),
        model=data.get("model"),
        priority=priority,
    )


def _stage_from_data(data: Any) -> Stage:
    """Parse one stage mapping with its steps."""
    if not isinstance(data, dict):
        raise WorkflowInvalid(["stages: every stage must be a mapping"])
    if not isinstance(data.get("name"), str) or not data.get("name"):
        raise WorkflowInvalid(["stage: name is required and must not be empty"])
    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list):
        raise WorkflowInvalid([f"stage {data.get('name')!r}: steps must be a list"])
    return Stage(
        name=str(data["name"]),
        steps=tuple(_step_from_data(item) for item in steps_raw),
    )


def _step_from_data(data: Any) -> Step:
    """Parse one step mapping with its optional worker fields."""
    if not isinstance(data, dict):
        raise WorkflowInvalid(["steps: every step must be a mapping"])
    for key in ("name", "title"):
        if not isinstance(data.get(key), str):
            raise WorkflowInvalid([f"step: {key} is required and must be a string"])
    description = data.get("description", "")
    if not isinstance(description, str):
        raise WorkflowInvalid([f"step {data.get('name')!r}: description must be a string"])
    needs = _needs_from_data(data.get("name"), data.get("needs"))
    priority = data.get("priority")
    if priority is not None and (not isinstance(priority, int) or isinstance(priority, bool)):
        raise WorkflowInvalid([f"step {data.get('name')!r}: priority must be an integer"])
    return Step(
        name=str(data["name"]),
        title=str(data["title"]),
        description=description,
        cwd=_field_or_none(data, "cwd", str),
        coder=_field_or_none(data, "coder", str),
        model=_field_or_none(data, "model", str),
        priority=priority,
        needs=needs,
    )


def _needs_from_data(step_name: Any, raw: Any) -> tuple[str, ...]:
    """Parse one step's needs list (absent means fan-in from the previous stage)."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise WorkflowInvalid([f"step {step_name!r}: needs must be a list of strings"])
    return tuple(raw)


def _field_or_none(data: dict[str, Any], key: str, kind: type) -> Any:
    """Read an optional step field, rejecting values of the wrong type."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, kind):
        raise WorkflowInvalid([f"step {data.get('name')!r}: {key} must be a string"])
    return value
