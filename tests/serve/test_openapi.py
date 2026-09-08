"""Tests for serve/api/models.py and the generated UI contract (ADR 0006 rule 4)."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from fleet.core.config import RuntimeConfig
from fleet.serve.api import models
from fleet.serve.app import create_app


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Serve app built against a throwaway fleet home (no daemon starts)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    return create_app()


def _api_routes(app) -> list[APIRoute]:
    """HTTP routes under /api/ (websockets have no response model)."""
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api")
    ]


def test_every_api_route_has_response_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every route under /api/ declares a pydantic response_model (FR-07)."""
    missing = [
        f"{sorted(route.methods)} {route.path}"
        for route in _api_routes(_app(tmp_path, monkeypatch))
        if route.response_model is None
    ]
    assert missing == []


def test_openapi_schema_builds_with_ref_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """app.openapi() builds and every /api/ op answers 200 with a model ref."""
    schema = _app(tmp_path, monkeypatch).openapi()
    assert "components" in schema and "schemas" in schema["components"]
    unrefed = []
    for path, item in schema["paths"].items():
        if not path.startswith("/api"):
            continue
        for method, op in item.items():
            if not isinstance(op, dict) or "responses" not in op:
                continue
            ok = op["responses"].get("200", {})
            body = json_body_ref(ok)
            if body is None:
                unrefed.append(f"{method.upper()} {path}")
    assert unrefed == []


def json_body_ref(ok_response: dict) -> str | None:
    """$ref of a 200 JSON body, or None when the op answers without one."""
    try:
        return ok_response["content"]["application/json"]["schema"]["$ref"]
    except (KeyError, TypeError):
        return None


def test_config_view_matches_runtime_config() -> None:
    """ConfigView field names track core.config.RuntimeConfig (no drift)."""
    expected = {f.name for f in fields(RuntimeConfig)}
    assert set(models.ConfigView.model_fields) == expected


def test_task_detail_extends_task_summary() -> None:
    """TaskDetail carries every TaskSummary field plus the attempts timeline."""
    assert set(models.TaskSummary.model_fields) <= set(models.TaskDetail.model_fields)
    assert "attempts" in models.TaskDetail.model_fields


def test_request_models_accept_ui_payloads() -> None:
    """Request models validate the shapes the UI's api.ts sends."""
    assert models.CreateTaskRequest.model_validate({"title": "x"}).title == "x"
    full = models.CreateTaskRequest.model_validate(
        {
            "title": "x",
            "description": "d",
            "cwd": "/tmp",
            "coder": "claude",
            "model": "sonnet",
            "priority": 1,
            "dependencies": ["a"],
            "args": "--x",
        }
    )
    assert full.dependencies == ["a"]
    assert models.UnblockRequest.model_validate({"note": "n"}).note == "n"
    assert models.UnblockRequest.model_validate({}).note is None
    assert models.SetBeadStatusRequest.model_validate({"status": "open"}).status == "open"
    assert models.AnswerRequest.model_validate({"answer": ["a", "b"]}).answer == ["a", "b"]
    assert models.ConfigUpdateRequest.model_validate({"max_concurrent": 2}).max_concurrent == 2
