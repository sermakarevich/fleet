"""Tests for fleet-ask MCP server (FR-22, FR-23, FR-24, FR-25, FR-30)."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from fleet.serve.app import create_app
from fleet.serve.mcp import DEFAULT_ANSWER, PendingQuestionStore


def _call(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}


def _setup_task_dir(tmp_path: Path, task_id: str) -> Path:
    task_dir = tmp_path / "tasks" / task_id
    (task_dir / "artifacts").mkdir(parents=True)
    (task_dir / "artifacts" / "Q&A.md").write_text("")
    return task_dir


def test_mcp_tools_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /mcp tools/list returns ask_human tool definition (FR-22)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/mcp", json=_call("tools/list"))

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    tools = data["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "ask_human"
    assert "question" in tools[0]["inputSchema"]["properties"]


def test_mcp_ask_human_answered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ask_human blocks and returns answer when answered via /api/qa/{id}/answer (FR-24, FR-25)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _setup_task_dir(tmp_path, "task-ans")
    app = create_app()

    async def _run() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ask_task = asyncio.create_task(
                client.post(
                    "/mcp",
                    json=_call("tools/call", {
                        "name": "ask_human",
                        "arguments": {
                            "question": "Should we expose --flag?",
                            "choices": ["yes", "no"],
                            "timeout_sec": 10,
                        },
                    }),
                    headers={"X-Fleet-Task-ID": "task-ans"},
                )
            )
            await asyncio.sleep(0.05)
            store: PendingQuestionStore = app.state.pending_questions
            questions = store.list()
            assert len(questions) == 1
            q_id = questions[0].id
            answer_resp = await client.post(f"/api/qa/{q_id}/answer", json={"answer": "yes"})
            ask_resp = await ask_task
            return ask_resp, answer_resp

    ask_resp, answer_resp = asyncio.run(_run())
    assert answer_resp.status_code == 200
    assert ask_resp.status_code == 200
    data = ask_resp.json()
    assert data["result"]["content"][0]["text"] == "yes"


def test_mcp_ask_human_writes_qa_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ask_human appends ## Q: block to artifacts/Q&A.md (FR-23)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _setup_task_dir(tmp_path, "task-qa")
    qa_file = task_dir / "artifacts" / "Q&A.md"
    app = create_app()

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ask_task = asyncio.create_task(
                client.post(
                    "/mcp",
                    json=_call("tools/call", {
                        "name": "ask_human",
                        "arguments": {"question": "Is this correct?", "timeout_sec": 5},
                    }),
                    headers={"X-Fleet-Task-ID": "task-qa"},
                )
            )
            await asyncio.sleep(0.05)
            store: PendingQuestionStore = app.state.pending_questions
            q_id = store.list()[0].id
            await client.post(f"/api/qa/{q_id}/answer", json={"answer": "yes"})
            await ask_task

    asyncio.run(_run())
    content = qa_file.read_text()
    assert "## Q:" in content
    assert "Is this correct?" in content
    assert "fleet-ask" in content


def test_mcp_ask_human_writes_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ask_human appends ask_human event (kind in extra) to events.jsonl (FR-23)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    task_dir = _setup_task_dir(tmp_path, "task-ev")
    events_file = task_dir / "events.jsonl"
    app = create_app()

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ask_task = asyncio.create_task(
                client.post(
                    "/mcp",
                    json=_call("tools/call", {
                        "name": "ask_human",
                        "arguments": {"question": "Event test?", "timeout_sec": 5},
                    }),
                    headers={"X-Fleet-Task-ID": "task-ev"},
                )
            )
            await asyncio.sleep(0.05)
            store: PendingQuestionStore = app.state.pending_questions
            q_id = store.list()[0].id
            await client.post(f"/api/qa/{q_id}/answer", json={"answer": "yes"})
            await ask_task

    asyncio.run(_run())
    lines = [ln for ln in events_file.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    ev = json.loads(lines[0])
    extra = ev["extra"]
    assert extra["kind"] == "ask_human"
    assert extra["question"] == "Event test?"


def test_mcp_ask_human_broadcasts_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ask_human broadcasts WebSocket notification before blocking (FR-24)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _setup_task_dir(tmp_path, "task-ws")
    app = create_app()

    mgr = app.state.connection_manager
    broadcasts: list[dict] = []
    original_broadcast = mgr.broadcast

    async def _capturing(tid: str, payload: dict) -> None:
        broadcasts.append({"task_id": tid, "payload": payload})
        await original_broadcast(tid, payload)

    mgr.broadcast = _capturing

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ask_task = asyncio.create_task(
                client.post(
                    "/mcp",
                    json=_call("tools/call", {
                        "name": "ask_human",
                        "arguments": {"question": "Broadcast test?", "timeout_sec": 5},
                    }),
                    headers={"X-Fleet-Task-ID": "task-ws"},
                )
            )
            await asyncio.sleep(0.05)
            assert len(broadcasts) >= 1
            assert broadcasts[0]["payload"]["kind"] == "ask_human"
            assert broadcasts[0]["payload"]["extra"]["question"] == "Broadcast test?"
            store: PendingQuestionStore = app.state.pending_questions
            q_id = store.list()[0].id
            await client.post(f"/api/qa/{q_id}/answer", json={"answer": "yes"})
            await ask_task

    asyncio.run(_run())


def test_mcp_ask_human_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ask_human returns DEFAULT_ANSWER and marks status timed_out after timeout (FR-25)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _setup_task_dir(tmp_path, "task-to")
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=10
        ) as client:
            return await client.post(
                "/mcp",
                json=_call("tools/call", {
                    "name": "ask_human",
                    "arguments": {"question": "Will this timeout?", "timeout_sec": 1},
                }),
                headers={"X-Fleet-Task-ID": "task-to"},
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["content"][0]["text"] == DEFAULT_ANSWER
    store: PendingQuestionStore = app.state.pending_questions
    assert store.list()[0].status == "timed_out"


def test_mcp_ask_human_defer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defer sets status=deferred, calls bd update --status blocked, unblocks MCP call (FR-30)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _setup_task_dir(tmp_path, "task-def")
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ask_task = asyncio.create_task(
                client.post(
                    "/mcp",
                    json=_call("tools/call", {
                        "name": "ask_human",
                        "arguments": {"question": "Defer me?", "timeout_sec": 30},
                    }),
                    headers={"X-Fleet-Task-ID": "task-def"},
                )
            )
            await asyncio.sleep(0.05)
            store: PendingQuestionStore = app.state.pending_questions
            q_id = store.list()[0].id
            with patch("fleet.serve.mcp.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["bd", "update", "task-def", "--status", "blocked"],
                    returncode=0,
                    stdout="",
                    stderr="",
                )
                defer_resp = await client.post(f"/api/qa/{q_id}/defer")
                ask_resp = await ask_task
            assert defer_resp.status_code == 200
            assert store.list()[0].status == "deferred"
            mock_run.assert_called_once_with(
                ["bd", "update", "task-def", "--status", "blocked"],
                capture_output=True,
                text=True,
            )
            return ask_resp

    resp = asyncio.run(_run())
    assert resp.status_code == 200


def test_mcp_ask_human_defer_bd_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When bd update fails, defer returns 502 and the question remains open (TASKS 2.8)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _setup_task_dir(tmp_path, "task-fail")
    app = create_app()

    async def _run() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ask_task = asyncio.create_task(
                client.post(
                    "/mcp",
                    json=_call("tools/call", {
                        "name": "ask_human",
                        "arguments": {"question": "Fail defer?", "timeout_sec": 30},
                    }),
                    headers={"X-Fleet-Task-ID": "task-fail"},
                )
            )
            await asyncio.sleep(0.05)
            store: PendingQuestionStore = app.state.pending_questions
            q_id = store.list()[0].id
            with patch("fleet.serve.mcp.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(
                    args=["bd", "update", "task-fail", "--status", "blocked"],
                    returncode=1,
                    stdout="",
                    stderr="task not found",
                )
                defer_resp = await client.post(f"/api/qa/{q_id}/defer")
            assert defer_resp.status_code == 502
            assert "task not found" in defer_resp.json()["error"]
            assert store.list()[0].status == "open"
            ask_task.cancel()
            try:
                await ask_task
            except (asyncio.CancelledError, Exception):
                pass
            return defer_resp

    resp = asyncio.run(_run())
    assert resp.status_code == 502


def test_pending_question_persists_across_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Open question survives fleet serve restart and can still be answered (TASKS 2.7)."""
    monkeypatch.setenv("FLEET_HOME", str(tmp_path))
    _setup_task_dir(tmp_path, "task-persist")

    store_file = tmp_path / "pending_questions.json"

    # --- First "server instance": submit a question, leave it open ---
    app1 = create_app()

    async def _submit() -> str:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app1), base_url="http://test"
        ) as client:
            ask_task = asyncio.create_task(
                client.post(
                    "/mcp",
                    json=_call("tools/call", {
                        "name": "ask_human",
                        "arguments": {"question": "Persist me?", "timeout_sec": 60},
                    }),
                    headers={"X-Fleet-Task-ID": "task-persist"},
                )
            )
            await asyncio.sleep(0.05)
            store: PendingQuestionStore = app1.state.pending_questions
            questions = store.list()
            assert len(questions) == 1
            q_id = questions[0].id
            ask_task.cancel()
            try:
                await ask_task
            except (asyncio.CancelledError, Exception):
                pass
            return q_id

    q_id = asyncio.run(_submit())

    # Question must be written to disk while the first app was alive
    assert store_file.exists(), "store_file must exist after a question is added"
    persisted = json.loads(store_file.read_text())
    assert len(persisted) == 1
    assert persisted[0]["id"] == q_id
    assert persisted[0]["status"] == "open"

    # --- Second "server instance": simulate restart by creating a fresh app ---
    app2 = create_app()
    store2: PendingQuestionStore = app2.state.pending_questions
    restored = store2.list()
    assert len(restored) == 1, "question must be restored on startup"
    assert restored[0].id == q_id
    assert restored[0].status == "open"

    # The restored question can be answered via the API
    async def _answer() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app2), base_url="http://test"
        ) as client:
            return await client.post(
                f"/api/qa/{q_id}/answer", json={"answer": "still here"}
            )

    answer_resp = asyncio.run(_answer())
    assert answer_resp.status_code == 200
    assert answer_resp.json()["ok"] is True
    assert store2.list()[0].status == "answered"
    assert store2.list()[0].answer == "still here"

    # JSON file updated with answer
    updated = json.loads(store_file.read_text())
    assert updated[0]["status"] == "answered"
    assert updated[0]["answer"] == "still here"
