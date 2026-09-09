"""Bearer-token auth for `fleet serve`, one owner.

Called by serve/app.py (HTTP middleware, websocket checks). Token comes from
$FLEET_API_TOKEN; empty means open. Only /api/* is guarded (/healthz stays
public); websocket checks cover /ws/* (bead 23 hardens this further).
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response


def expected_token() -> str:
    """The configured API token, or empty when auth is disabled."""
    return os.environ.get("FLEET_API_TOKEN", "").strip()


def guarded_path(path: str) -> bool:
    """True when *path* requires a token (empty token still means open)."""
    return path.startswith("/api/")


def supplied_token(request: Request) -> str:
    """Token from `Authorization: Bearer` header, else the `?token=` query."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return request.query_params.get("token", "")


def websocket_authorized(websocket: WebSocket) -> bool:
    """True when the websocket may connect (token matches or auth disabled)."""
    token = expected_token()
    return not token or websocket.query_params.get("token", "") == token


def install_auth(app: FastAPI) -> None:
    """Guard /api/* with the bearer token; everything else passes through."""

    @app.middleware("http")
    async def _bearer_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        token = expected_token()
        if token and guarded_path(request.url.path) and supplied_token(request) != token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)
