"""Flow starts: cron, tool polling, manual (docs/27_sep_upgrade/DESIGN.md §3.5).

Evaluates each enabled flow's ``on:`` declaration once per flow-service tick:
a due cron expression starts a run with empty inputs, a due tool poll runs
the declared tool and starts one live run per item key (a key may start again
once its previous run has finished, after a short cooldown), and a person
starts a run through ``start_manual`` (CLI now, UI later).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fleet.core.errors import FlowInvalid
from fleet.core.limits import START_KEY_COOLDOWN_SEC
from fleet.flows.model import Flow
from fleet.flows.templates import render, render_mapping
from fleet.flows.tools import Tool
from fleet.pool.tool_run import run_tool
from fleet.runs import engine
from fleet.runs.store import Run, RunStore
from fleet.schedules.cron import next_fire

_EVERY_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([HMSmhs])\s*$")
_EVERY_SCALE = {"s": 1.0, "m": 60.0, "h": 3600.0}


@dataclass(frozen=True)
class StartClock:
    """Last time each start fired, kept in memory by the flow service."""

    cron_last: dict[str, datetime] = field(default_factory=dict)  # flow name → last fire considered
    tool_last: dict[str, datetime] = field(default_factory=dict)  # flow name → last poll


def due_cron(flow: Flow, last: datetime | None, now: datetime) -> bool:
    """True when next_fire(expr, after=last or now - 1 minute, tz) <= now."""
    cron = flow.on.cron
    if cron is None:
        return False
    after = last if last is not None else now - timedelta(minutes=1)
    return next_fire(cron.expr, after, cron.tz) <= now


def parse_every(text: str) -> float:
    """'30s' | '5m' | '2h' → seconds; raises ValueError otherwise."""
    match = _EVERY_RE.match(text or "")
    if match is None:
        raise ValueError(f"every: must look like '30s', '5m' or '2h', got {text!r}")
    return float(match.group(1)) * _EVERY_SCALE[match.group(2).lower()]


def _as_list(output: Any) -> list[Any] | None:
    """Unwrap tool output to a list: a list as is, else a single-list dict value."""
    if isinstance(output, list):
        return output
    if isinstance(output, dict) and len(output) == 1:
        sole = next(iter(output.values()))
        if isinstance(sole, list):
            return sole
    return None


def _in_cooldown(store: RunStore, flow_name: str, key: str, now: datetime) -> bool:
    """Whether the key's newest finished run ended less than the cooldown ago."""
    last = store.last_finished_at(flow_name, key)
    if last is None:
        return False
    try:
        finished = datetime.fromisoformat(last)
    except ValueError:
        return False
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    return (now - finished).total_seconds() < START_KEY_COOLDOWN_SEC


async def poll_tool_start(
    flow: Flow,
    tool: Tool,
    store: RunStore,
    fleet_home: Path,
    now: datetime,
    *,
    environ: Mapping[str, str],
    log: Any,
) -> list[Run]:
    """Poll one flow's ``on.tool``; start one live run per item key."""
    spec = flow.on.tool
    if spec is None:
        return []
    try:
        given = render_mapping(spec.args, {"now": now, "defaults": dict(flow.defaults)})
    except Exception as exc:  # noqa: BLE001 - a bad template fails the poll, not the tick
        log.warning("start_tool_failed", flow=flow.name, tool=tool.name, reason=str(exc))
        return []
    stamp = now.strftime("%Y%m%dT%H%M%S-%f")
    attempt_dir = fleet_home / "starts" / flow.name / stamp
    try:
        result = await run_tool(
            tool, given, cwd=fleet_home, attempt_dir=attempt_dir, environ=environ
        )
    except Exception as exc:  # noqa: BLE001 - a spawn failure fails the poll, not the tick
        log.warning("start_tool_failed", flow=flow.name, tool=tool.name, reason=str(exc))
        return []
    if not result.ok:
        log.warning(
            "start_tool_failed",
            flow=flow.name,
            tool=tool.name,
            reason=result.stderr or f"exit {result.exit_code}",
        )
        return []
    items = _as_list(result.output)
    if items is None:
        log.warning("start_tool_bad_output", flow=flow.name, tool=tool.name)
        return []
    declared = {item.name for item in flow.inputs}
    started: list[Run] = []
    for item in items:
        if not isinstance(item, Mapping):
            log.warning(
                "start_tool_bad_output",
                flow=flow.name,
                tool=tool.name,
                reason="item is not a mapping",
            )
            continue
        try:
            key = render(
                spec.key,
                {"item": dict(item), "now": now, "defaults": dict(flow.defaults)},
            )
        except Exception as exc:  # noqa: BLE001 - a bad key skips the item, not the poll
            log.warning("start_tool_bad_output", flow=flow.name, tool=tool.name, reason=str(exc))
            continue
        if store.has_start_key(flow.name, key):
            log.debug("start_key_live", flow=flow.name, key=key)
            continue
        if _in_cooldown(store, flow.name, key, now):
            log.debug("start_key_cooldown", flow=flow.name, key=key)
            continue
        try:
            run = engine.start_run(
                store,
                fleet_home,
                flow,
                {name: value for name, value in item.items() if name in declared},
                now,
                start_key=key,
            )
        except FlowInvalid as exc:
            log.warning("start_item_invalid", flow=flow.name, key=key, reason=str(exc))
            continue
        started.append(run)
    return started


def start_manual(
    store: RunStore, fleet_home: Path, flow: Flow, given: Mapping[str, Any], now: datetime
) -> Run:
    """Start a run by hand; raise when the flow disables manual starts."""
    if not flow.on.manual:
        raise FlowInvalid(f"flow {flow.name}: manual start disabled")
    return engine.start_run(store, fleet_home, flow, given, now)
