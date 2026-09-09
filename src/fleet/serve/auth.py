"""Bearer-token auth for `fleet serve`, one owner.

Called by ``serve/app.py`` (router-level dependencies) and every ``serve/api/``
router (``dependencies=[Depends(require_token)]``). The token comes from
``$FLEET_API_TOKEN``; empty means the API is open. HTTP routes accept only
headers (``Authorization: Bearer`` or ``X-Fleet-Token``) so tokens never land
in access logs; websocket routes additionally accept ``?token=`` because
browsers cannot set headers on websockets. Comparison is constant-time.
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import Depends, Request, WebSocket

from fleet.serve.errors import unauthorized

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def expected_token() -> str:
    """The configured API token, or empty when auth is disabled."""
    return os.environ.get("FLEET_API_TOKEN", "").strip()


def _header_token(request: Request | WebSocket) -> str:
    """Token from `Authorization: Bearer` or `X-Fleet-Token` headers only."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-fleet-token", "").strip()


def _tokens_match(supplied: str) -> bool:
    """Constant-time token check; empty expected token means open."""
    expected = expected_token()
    if not expected:
        return True
    if not supplied:
        return False
    return secrets.compare_digest(supplied, expected)


async def require_token(request: Request) -> None:
    """HTTP dependency: reject with 401 unless a header token matches."""
    if not _tokens_match(_header_token(request)):
        raise unauthorized()


async def require_ws_token(websocket: WebSocket) -> bool:
    """Websocket guard: True when headers or `?token=` match, else close 4401.

    Returns a bool (instead of raising) because the endpoint must close the
    handshake itself; a raised HTTPException here would surface as an
    abnormal closure instead of the clean 4401 the UI expects. Endpoints
    declare ``allowed: bool = Depends(require_ws_token)`` and return early
    when it is False.
    """
    supplied = _header_token(websocket) or websocket.query_params.get("token", "").strip()
    if _tokens_match(supplied):
        return True
    await websocket.close(code=4401)
    return False


def warn_if_exposed(host: str | None) -> None:
    """Warn when the API has no token and the bind is not loopback-only."""
    if expected_token():
        return
    if host is not None and host in _LOOPBACK_HOSTS:
        return
    logger.warning("api has no token and binds non-loopback")


#: Router-level guard for every HTTP router: ``APIRouter(dependencies=[HTTP_AUTH])``.
HTTP_AUTH = Depends(require_token)

#: Router-level guard for websocket routers: ``APIRouter(dependencies=[WS_AUTH])``.
WS_AUTH = Depends(require_ws_token)
