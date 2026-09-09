"""Injected serve state, one owner.

Called by serve/app.py (builds it) and every serve/api/* router (takes it via
``get_state``). Routers never touch ``request.app.state`` directly. The
telegram listener gets its dependencies (api token, question store, command
env, offset file) built from here by create_app — never app.state itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from fleet.beads.queue import BeadsQueue, Queue
from fleet.core.config import RuntimeConfig
from fleet.integrations.ask_human.store import QuestionStore
from fleet.integrations.mcp_servers import ask_human_db_path
from fleet.serve.event_stream import FileWatcher, WebSocketBroadcaster
from fleet.state import paths as state_paths
from fleet.state.config_file import load as load_config


@dataclass
class AppState:
    """Everything a serve handler needs, injected instead of module globals."""

    fleet_home: Path
    queue: Queue
    question_store: QuestionStore
    config_path: Path
    watcher: FileWatcher
    connection_manager: WebSocketBroadcaster = field(repr=False)
    config: RuntimeConfig | None = None
    config_mtime: float | None = None
    telegram_token: str = ""
    """Telegram bot token, read once from the environment at startup."""


def build_state(queue: Queue | None = None) -> AppState:
    """Build the state for create_app; refreshes config in the lifespan."""
    fleet_home = state_paths.fleet_home()
    mgr = WebSocketBroadcaster()
    return AppState(
        fleet_home=fleet_home,
        queue=queue if queue is not None else BeadsQueue(fleet_home),
        question_store=QuestionStore(ask_human_db_path(fleet_home)),
        config_path=fleet_home / "runtime.toml",
        watcher=FileWatcher(mgr=mgr),
        connection_manager=mgr,
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    )


def refresh_config(state: AppState) -> AppState:
    """(Re)load runtime.toml into *state*; returns the same object."""
    state.fleet_home = state_paths.fleet_home()
    state.config_path = state.fleet_home / "runtime.toml"
    state.config = load_config(state.config_path)
    try:
        state.config_mtime = (
            state.config_path.stat().st_mtime if state.config_path.exists() else None
        )
    except OSError:
        state.config_mtime = None
    return state


def get_state(request: HTTPConnection) -> AppState:
    """FastAPI dependency returning the injected AppState (HTTP and websocket)."""
    return request.app.state.fleet_state


#: Handler parameter alias: `state: StateDep` injects AppState via get_state.
StateDep = Annotated[AppState, Depends(get_state)]
