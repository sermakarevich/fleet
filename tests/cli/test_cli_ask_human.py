"""Tests for the `fleet ask-human` CLI commands (vendored question broker)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from fleet.ask_human.store import QuestionStore
from fleet.cli import app

runner = CliRunner()


def _env(tmp_path: Path) -> dict[str, str]:
    return {"ASK_HUMAN_DB": str(tmp_path / "q.db")}


def _store(tmp_path: Path) -> QuestionStore:
    return QuestionStore(tmp_path / "q.db")


def test_ask_human_help_lists_commands() -> None:
    result = runner.invoke(app, ["ask-human", "--help"])
    assert result.exit_code == 0
    for cmd in ("serve", "list", "answer", "watch", "web", "install"):
        assert cmd in result.output


def test_list_empty(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ask-human", "list"], env=_env(tmp_path))
    assert result.exit_code == 0
    assert "no pending questions" in result.output


def test_list_shows_pending_question(tmp_path: Path) -> None:
    qid = _store(tmp_path).create("Deploy?", options=["yes", "no"], agent_id="agent-7")
    result = runner.invoke(app, ["ask-human", "list"], env=_env(tmp_path))
    assert result.exit_code == 0
    assert qid[:8] in result.output
    assert "Deploy?" in result.output
    assert "agent-7" in result.output


def test_answer_by_prefix_records_cli_answer(tmp_path: Path) -> None:
    s = _store(tmp_path)
    qid = s.create("Deploy?", options=["yes", "no"])
    result = runner.invoke(app, ["ask-human", "answer", qid[:6], "yes"], env=_env(tmp_path))
    assert result.exit_code == 0
    assert "answered" in result.output
    q = s.get(qid)
    assert q["status"] == "answered"
    assert q["answer"] == "yes"
    assert q["answered_by"] == "cli"


def test_answer_with_pipe_note(tmp_path: Path) -> None:
    s = _store(tmp_path)
    qid = s.create("Deploy?", options=["yes", "no"])
    result = runner.invoke(
        app, ["ask-human", "answer", qid[:6], "yes | wait for the migration"], env=_env(tmp_path)
    )
    assert result.exit_code == 0
    q = s.get(qid)
    assert q["answer"] == "yes"
    assert q["note"] == "wait for the migration"


def test_answer_unknown_prefix_reports_no_match(tmp_path: Path) -> None:
    result = runner.invoke(app, ["ask-human", "answer", "deadbeef", "yes"], env=_env(tmp_path))
    assert "no question matching" in result.output


def test_answer_already_resolved_reports_status(tmp_path: Path) -> None:
    s = _store(tmp_path)
    qid = s.create("Deploy?")
    s.answer(qid, "yes")
    result = runner.invoke(app, ["ask-human", "answer", qid[:6], "no"], env=_env(tmp_path))
    assert "already answered" in result.output
    assert s.get(qid)["answer"] == "yes"  # first writer kept


def test_install_requires_claude_cli(tmp_path: Path) -> None:
    with patch("shutil.which", return_value=None):
        result = runner.invoke(app, ["ask-human", "install"])
    assert result.exit_code == 1
    assert "claude" in result.output


def test_install_registers_with_claude_mcp_add() -> None:
    calls: list[list[str]] = []

    class _Done:
        returncode = 0
        stderr = ""

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return _Done()

    def fake_which(name):
        return {"claude": "/usr/local/bin/claude", "fleet": "/usr/local/bin/fleet"}.get(name)

    with patch("shutil.which", side_effect=fake_which), patch("fleet.cli.subprocess.run", side_effect=fake_run):
        result = runner.invoke(app, ["ask-human", "install"])

    assert result.exit_code == 0
    assert "Registered MCP server 'ask_human'" in result.output
    add = [c for c in calls if c[1:3] == ["mcp", "add"]]
    assert len(add) == 1
    assert add[0] == [
        "/usr/local/bin/claude", "mcp", "add", "ask_human", "--scope", "user",
        "--", "/usr/local/bin/fleet", "ask-human", "serve",
    ]
