"""Serve HTTP errors: one JSON shape for every failure.

Called by every module under ``serve/api/`` (``raise not_found(...)`` instead
of hand-built ``JSONResponse({"error": ...})``) and wired once in
``serve/app.py`` (``register_error_handlers``). The UI reads ``{"error": ...}``
on failures, so the handler renders exactly that body for every raised
``HTTPException`` — including auth rejections — and for FastAPI request
validation errors (out-of-range query params, missing required params).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def not_found(what: str, ident: str) -> HTTPException:
    """404 for a missing resource, e.g. ``not_found("task", task_id)``."""
    return HTTPException(status_code=404, detail=f"{what} not found: {ident}")


def bad_request(msg: str) -> HTTPException:
    """400 for a malformed request body the client can fix and retry."""
    return HTTPException(status_code=400, detail=msg)


def unprocessable(msg: str) -> HTTPException:
    """422 for a well-formed request whose values are rejected."""
    return HTTPException(status_code=422, detail=msg)


def bad_gateway(msg: str) -> HTTPException:
    """502 when the beads backend (`bd`) fails behind the API."""
    return HTTPException(status_code=502, detail=msg)


def conflict(msg: str) -> HTTPException:
    """409 when the request clashes with current state (taken name, busy run)."""
    return HTTPException(status_code=409, detail=msg)


def unauthorized() -> HTTPException:
    """401 for a missing or wrong API token."""
    return HTTPException(status_code=401, detail="unauthorized")


async def parse_json_body(request: Request) -> Any:
    """Decoded JSON body, or a raised 400 when the bytes are not JSON."""
    try:
        return await request.json()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        raise bad_request(f"malformed JSON body: {exc}") from exc


def _error_body(detail: object) -> dict[str, str]:
    """The one error shape the UI reads: ``{"error": ...}``."""
    if isinstance(detail, str):
        return {"error": detail}
    return {"error": str(detail)}


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render any HTTPException as the one error shape with its status."""
    if isinstance(exc, HTTPException | StarletteHTTPException):
        return JSONResponse(_error_body(exc.detail), status_code=exc.status_code)
    return JSONResponse({"error": "internal error"}, status_code=500)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render query/body validation failures (422) in the one error shape."""
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    first = errors[0] if errors else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) if isinstance(first, dict) else ""
    msg = first.get("msg", "invalid request") if isinstance(first, dict) else "invalid request"
    return JSONResponse({"error": f"{loc}: {msg}".strip(": ")}, status_code=422)


def register_error_handlers(app: FastAPI) -> None:
    """Wire the one error shape for HTTP and validation errors."""
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
