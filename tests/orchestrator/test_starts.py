"""Tests for orchestrator/starts.py and its flow-service tick wiring."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fleet.core.clock import FakeClock
from fleet.core.config import RuntimeConfig
from fleet.core.errors import FlowInvalid
from fleet.flows.model import Cron, Flow, Input, On, Step, ToolStart
from fleet.flows.tools import tool_from_dict
from fleet.orchestrator.flow_service import on_start, tick
from fleet.orchestrator.starts import due_cron, parse_every, poll_tool_start, start_manual
from fleet.runs.store import RunStore
from tests.conftest import FakeQueue, make_supervisor

NOW = datetime(2026, 9, 28, 7, 0, 0, tzinfo=UTC)

ECHOER_TOOL = """\
fleet_tool: 2
description: Print a fixed object.
command: ["python3", "-c", "import json; print(json.dumps({'n': 1}))"]
args: {}
env: []
output: json
timeout: 30
"""


class FakeLog:
    """Capture structlog-style (event, kwargs) calls."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def warning(self, event: str, **kw) -> None:
        self.events.append((event, kw))

    def info(self, event: str, **kw) -> None:
        self.events.append((event, kw))

    def names(self) -> list[str]:
        return [event for event, _ in self.events]


def _tool(name: str, command: list[str], output: str = "json"):
    return tool_from_dict(
        {
            "fleet_tool": 2,
            "description": "test tool",
            "command": command,
            "args": {},
            "env": [],
            "output": output,
            "timeout": 30,
        },
        name,
    )


def _flow(
    tmp_path: Path,
    name: str = "demo",
    inputs: tuple = (),
    on: On | None = None,
) -> Flow:
    source = tmp_path / f"{name}.yaml"
    source.write_text("fleet_flow: 2\n", encoding="utf-8")
    return Flow(
        name=name,
        inputs=inputs,
        steps=(Step(name="a", prompt="do a"),),
        on=on if on is not None else On(),
        source=str(source),
    )


def _tool_flow(tmp_path: Path, items: str) -> tuple[Flow, object]:
    """A flow polling a tool that prints *items* (a JSON expression)."""
    tool = _tool(
        "lister",
        ["python3", "-c", f"import json; print(json.dumps({items}))"],
    )
    flow = _flow(
        tmp_path,
        inputs=(Input(name="repo", required=True),),
        on=On(tool=ToolStart(name="lister", every="30s")),
    )
    return flow, tool


def _home(tmp_path: Path) -> Path:
    fleet_home = tmp_path / "home"
    fleet_home.mkdir(parents=True, exist_ok=True)
    return fleet_home


# --- due_cron ---


def test_due_cron_at_boundary_last_none(tmp_path: Path) -> None:
    """Every-minute flow with no last fire is due exactly at the minute."""
    flow = _flow(tmp_path, on=On(cron=Cron(expr="* * * * *", tz="UTC")))
    assert due_cron(flow, None, NOW) is True


def test_due_cron_before_boundary_last_none(tmp_path: Path) -> None:
    """A 07:00 flow is not due at 06:59 but is due at 07:00."""
    flow = _flow(tmp_path, on=On(cron=Cron(expr="0 7 * * *", tz="UTC")))
    before = datetime(2026, 9, 28, 6, 59, 0, tzinfo=UTC)
    assert due_cron(flow, None, before) is False
    assert due_cron(flow, None, NOW) is True


def test_due_cron_second_tick_same_minute(tmp_path: Path) -> None:
    """Once fired, the same minute is not due again."""
    flow = _flow(tmp_path, on=On(cron=Cron(expr="* * * * *", tz="UTC")))
    assert due_cron(flow, NOW, NOW) is False


def test_due_cron_no_cron_never_due(tmp_path: Path) -> None:
    assert due_cron(_flow(tmp_path), None, NOW) is False


# --- parse_every ---


def test_parse_every_units_and_bad_string() -> None:
    assert parse_every("30s") == 30.0
    assert parse_every("5m") == 300.0
    assert parse_every("2h") == 7200.0
    with pytest.raises(ValueError):
        parse_every("bogus")


# --- poll_tool_start ---


def test_poll_starts_two_runs_then_dedupes(tmp_path: Path) -> None:
    """Two items start two keyed runs; a second poll starts none."""
    flow, tool = _tool_flow(tmp_path, "[{'id': 'a', 'repo': 'x'}, {'id': 'b', 'repo': 'y'}]")
    fleet_home = _home(tmp_path)
    store = RunStore(fleet_home / "runs.db")
    log = FakeLog()
    first = asyncio.run(poll_tool_start(flow, tool, store, fleet_home, NOW, environ={}, log=log))
    assert [run.start_key for run in first] == ["a", "b"]
    assert all(run.flow == "demo" for run in first)
    assert store.has_start_key("demo", "a") and store.has_start_key("demo", "b")
    second = asyncio.run(poll_tool_start(flow, tool, store, fleet_home, NOW, environ={}, log=log))
    assert second == []
    assert len(store.list_runs(flow="demo")) == 2


def test_poll_skips_item_missing_required_input(tmp_path: Path) -> None:
    """An item without the required input is skipped and logged."""
    flow, tool = _tool_flow(tmp_path, "[{'id': 'a', 'repo': 'x'}, {'id': 'b'}]")
    fleet_home = _home(tmp_path)
    store = RunStore(fleet_home / "runs.db")
    log = FakeLog()
    started = asyncio.run(poll_tool_start(flow, tool, store, fleet_home, NOW, environ={}, log=log))
    assert [run.start_key for run in started] == ["a"]
    assert "start_item_invalid" in log.names()
    assert not store.has_start_key("demo", "b")


def test_poll_non_list_output_starts_none(tmp_path: Path) -> None:
    """A dict without a single list value is bad output: no runs, one log."""
    tool = _tool("lister", ["python3", "-c", "print('{\"a\": 1}')"])
    flow = _flow(
        tmp_path,
        inputs=(Input(name="repo", required=True),),
        on=On(tool=ToolStart(name="lister", every="30s")),
    )
    fleet_home = _home(tmp_path)
    store = RunStore(fleet_home / "runs.db")
    log = FakeLog()
    assert (
        asyncio.run(poll_tool_start(flow, tool, store, fleet_home, NOW, environ={}, log=log)) == []
    )
    assert "start_tool_bad_output" in log.names()
    assert store.list_runs(flow="demo") == []


def test_poll_failed_tool_starts_none(tmp_path: Path) -> None:
    """A non-zero exit logs start_tool_failed and starts nothing."""
    tool = _tool("failer", ["python3", "-c", "import sys; sys.exit(1)"], output="text")
    flow = _flow(tmp_path, on=On(tool=ToolStart(name="failer", every="30s")))
    fleet_home = _home(tmp_path)
    store = RunStore(fleet_home / "runs.db")
    log = FakeLog()
    assert (
        asyncio.run(poll_tool_start(flow, tool, store, fleet_home, NOW, environ={}, log=log)) == []
    )
    assert "start_tool_failed" in log.names()


# --- start_manual ---


def test_start_manual_disabled_raises(tmp_path: Path) -> None:
    flow = _flow(tmp_path, on=On(manual=False))
    fleet_home = _home(tmp_path)
    with pytest.raises(FlowInvalid, match="manual start disabled"):
        start_manual(RunStore(fleet_home / "runs.db"), fleet_home, flow, {}, NOW)


def test_start_manual_enabled_starts(tmp_path: Path) -> None:
    flow = _flow(tmp_path, on=On(manual=True))
    fleet_home = _home(tmp_path)
    run = start_manual(RunStore(fleet_home / "runs.db"), fleet_home, flow, {}, NOW)
    assert run.flow == "demo" and run.start_key is None


# --- tick wiring ---


def _catalog(tmp_path: Path, flows: dict[str, str], tools: dict[str, str]) -> Path:
    root = tmp_path / "catalog"
    (root / "flows").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    for name, text in flows.items():
        (root / "flows" / f"{name}.yaml").write_text(text, encoding="utf-8")
    for name, text in tools.items():
        (root / "tools" / f"{name}.yaml").write_text(text, encoding="utf-8")
    return root


def test_tick_starts_due_cron_once(tmp_path: Path) -> None:
    """A due cron flow gains one run on tick 1 and none on tick 2."""
    catalog = _catalog(
        tmp_path,
        {
            "demo": (
                "fleet_flow: 2\n\"on\":\n  cron:\n    expr: '* * * * *'\n"
                "steps:\n  a:\n    kind: tool\n    tool: echoer\n"
            )
        },
        {"echoer": ECHOER_TOOL},
    )
    config = RuntimeConfig(flows_folders=[str(catalog)], isolation="none")
    sup = make_supervisor(tmp_path, queue=FakeQueue(), config=config, services=[], checks=[])
    st = sup.state
    st.clock = FakeClock(start=NOW)
    asyncio.run(on_start(st))

    async def _main():
        await tick(st)
        first = st.flows.store.list_runs()
        await tick(st)
        second = st.flows.store.list_runs()
        await asyncio.sleep(0.3)
        await tick(st)
        return first, second

    first, second = asyncio.run(_main())
    assert len(first) == 1 and first[0].flow == "demo"
    assert len(second) == 1
    assert st.flows.starts.cron_last["demo"] == NOW
