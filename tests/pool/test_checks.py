"""Tests for fleet.pool.checks (real tiny tool commands, fake human store)."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fleet.core.errors import FlowNotFound
from fleet.flows.model import Check
from fleet.flows.tools import Tool, ToolArg
from fleet.pool.checks import (
    CheckOutcome,
    Verdict,
    decide,
    read_verdict,
    retry_feedback,
    run_checks,
    verdict_file,
    write_verdict,
)
from tests.pool.conftest import FakeStore


def _environ() -> dict[str, str]:
    """A real environment for child processes (needs PATH for python3)."""
    return dict(os.environ)


def _catalog(*tools: Tool):
    """A catalog fn raising KeyError for unknown names."""

    def _get(name: str) -> Tool:
        for tool in tools:
            if tool.name == name:
                return tool
        raise KeyError(name)

    return _get


def _attempt(tmp_path: Path) -> Path:
    """An attempt dir named "1" (human check contexts use it)."""
    return tmp_path / "attempts" / "1"


def _run(
    tmp_path: Path,
    checks: list[Check],
    ctx: Mapping[str, Any] | None = None,
    *,
    when: str = "after",
    tools=None,
    ask_store=None,
    run_coder_check=None,
) -> CheckOutcome:
    """Run checks with STOCK wiring over attempt "1"."""
    return asyncio.run(
        run_checks(
            checks,
            dict(ctx or {}),
            when=when,
            tools=tools or _catalog(),
            cwd=tmp_path,
            attempt_dir=_attempt(tmp_path),
            environ=_environ(),
            ask_store=ask_store,
            task_id="run1.draft",
            run_coder_check=run_coder_check,
        )
    )


def _text_tool(name: str, body: str) -> Tool:
    """A text-output tool running one inline python3 snippet."""
    return Tool(name=name, command=("python3", "-c", body), output="text")


def test_tool_check_pass(tmp_path: Path) -> None:
    """Exit 0 passes; the message is stdout stripped."""
    tool = _text_tool("lint", "print('  all good\\n')")
    check = Check(name="lint", tool="lint")
    outcome = _run(tmp_path, [check], tools=_catalog(tool))
    assert outcome.ok and outcome.failed is None
    (verdict,) = outcome.verdicts
    assert (verdict.name, verdict.ok, verdict.message) == ("lint", True, "all good")
    assert verdict.outputs is None and verdict.kind == "tool"
    assert verdict.duration_s >= 0.0
    # run_tool wrote its attempt files under checks/<name>/ ...
    assert (_attempt(tmp_path) / "checks" / "lint" / "stdout.txt").is_file()
    # ... and the verdict file sits next to it, readable.
    assert read_verdict(verdict_file(_attempt(tmp_path), "lint")) == verdict


def test_tool_check_fail_stops_list(tmp_path: Path) -> None:
    """A nonzero exit fails; later checks never run."""
    fail = _text_tool("bad", "import sys; print('oops'); sys.exit(3)")
    never = _text_tool("never", "print('ran')")
    checks = [Check(name="first", tool="bad"), Check(name="second", tool="never")]
    outcome = _run(tmp_path, checks, tools=_catalog(fail, never))
    assert not outcome.ok and outcome.failed is not None and outcome.failed.name == "first"
    assert [verdict.name for verdict in outcome.verdicts] == ["first"]
    assert outcome.verdicts[0].message == "oops"
    assert not verdict_file(_attempt(tmp_path), "second").exists()


def test_tool_message_json_wins_over_stdout(tmp_path: Path) -> None:
    """A dict output's message beats stdout; the dict becomes outputs."""
    body = "import json; print(json.dumps({'message': 'json wins', 'n': 2}))"
    tool = Tool(name="judge", command=("python3", "-c", body), output="json")
    outcome = _run(tmp_path, [Check(name="judge", tool="judge")], tools=_catalog(tool))
    (verdict,) = outcome.verdicts
    assert verdict.ok and verdict.message == "json wins"
    assert verdict.outputs == {"message": "json wins", "n": 2}


def test_tool_message_stdout_then_stderr(tmp_path: Path) -> None:
    """Stdout wins when json has no message; stderr wins when stdout is empty."""
    plain = Tool(
        name="plain",
        command=("python3", "-c", "import json; print(json.dumps({'n': 1}))"),
        output="json",
    )
    outcome = _run(tmp_path, [Check(name="plain", tool="plain")], tools=_catalog(plain))
    assert outcome.verdicts[0].outputs == {"n": 1}
    assert outcome.verdicts[0].message == '{"n": 1}'
    err = _text_tool("err", "import sys; sys.stderr.write('boom\\n'); sys.exit(1)")
    outcome = _run(tmp_path, [Check(name="err", tool="err")], tools=_catalog(err))
    assert not outcome.ok and outcome.verdicts[0].message == "boom"


def test_tool_args_rendered_over_ctx(tmp_path: Path) -> None:
    """Check args render over ctx before the tool runs."""
    tool = Tool(
        name="echoer",
        command=("python3", "-c", "import sys; print(sys.argv[1])", "{{ args.word }}"),
        args=(ToolArg(name="word", required=True),),
        output="text",
    )
    check = Check(name="echo", tool="echoer", args={"word": "{{ outputs.word }}"})
    outcome = _run(tmp_path, [check], {"outputs": {"word": "hi"}}, tools=_catalog(tool))
    assert outcome.ok and outcome.verdicts[0].message == "hi"


def test_unknown_tool_fails(tmp_path: Path) -> None:
    """KeyError and FlowNotFound from the catalog both fail the check."""

    def _missing(name: str) -> Tool:
        raise FlowNotFound(name)

    for tools in (_catalog(), _missing):
        outcome = _run(tmp_path, [Check(name="lint", tool="nope")], tools=tools)
        assert not outcome.ok
        assert outcome.verdicts[0].message == "unknown tool nope"
        assert outcome.failed is not None and outcome.failed.name == "lint"


def test_skip_if_true_records_skipped(tmp_path: Path) -> None:
    """A true skip_if passes with "skipped" and the list goes on."""
    tool = _text_tool("lint", "print('ran')")
    checks = [
        Check(name="guard", tool="lint", skip_if="{{ outputs.skip }}"),
        Check(name="lint", tool="lint"),
    ]
    outcome = _run(tmp_path, checks, {"outputs": {"skip": True}}, tools=_catalog(tool))
    assert outcome.ok
    assert [(v.name, v.message) for v in outcome.verdicts] == [
        ("guard", "skipped"),
        ("lint", "ran"),
    ]
    outcome = _run(tmp_path, checks, {"outputs": {"skip": False}}, tools=_catalog(tool))
    assert outcome.ok and outcome.verdicts[0].message == "ran"


def test_when_filters_checks(tmp_path: Path) -> None:
    """Only checks with the requested `when` run."""
    tool = _text_tool("lint", "print('ran')")
    checks = [
        Check(name="pre", tool="lint", when="before"),
        Check(name="post", tool="lint", when="after"),
    ]
    before = _run(tmp_path, checks, when="before", tools=_catalog(tool)).verdicts
    assert [v.name for v in before] == ["pre"]
    after = _run(tmp_path, checks, when="after", tools=_catalog(tool)).verdicts
    assert [v.name for v in after] == ["post"]


def _preanswer(store: FakeStore, answer: Any, note: str | None) -> None:
    """Resolve the gate question before run_checks asks it (no waiting)."""
    qid = store.ask("Post?", ["yes", "no"], task_id="run1.draft", context="check:gate:1")
    store.answer(qid, answer, note=note)


def test_human_yes_and_no(tmp_path: Path) -> None:
    """yes passes; no fails; the note (else answer) is the message."""
    for answer, note, ok, message in [
        ("yes", "posted!", True, "posted!"),
        ("no", "not yet", False, "not yet"),
        ("no", None, False, "no"),
    ]:
        store = FakeStore()
        _preanswer(store, answer, note)
        check = Check(name="gate", kind="human", prompt="Post?")
        outcome = _run(tmp_path, [check], ask_store=store)
        assert outcome.ok is ok
        assert outcome.verdicts[0].message == message
        assert store.ask_count == 1  # already answered: asked nothing new


def test_human_live_question_wiring(tmp_path: Path) -> None:
    """A fresh human check asks yes/no with the rendered prompt and context."""
    store = FakeStore()
    check = Check(name="gate", kind="human", prompt="Post {{ outputs.reply }}?", on_fail="skip")

    async def _main() -> CheckOutcome:
        async def _answer() -> None:
            await asyncio.sleep(0.1)
            pending = store.find_pending("run1.draft", "check:gate:1")
            assert pending is not None
            assert pending.get("prompt") == "Post hello?"
            assert pending.get("options") == ["yes", "no"]
            store.answer(pending.get("id"), "yes", note="posted!")

        task = asyncio.create_task(_answer())
        outcome = await run_checks(
            [check],
            {"outputs": {"reply": "hello"}},
            when="after",
            tools=_catalog(),
            cwd=tmp_path,
            attempt_dir=_attempt(tmp_path),
            environ=_environ(),
            ask_store=store,
            task_id="run1.draft",
            run_coder_check=None,
        )
        await task
        return outcome

    outcome = asyncio.run(_main())
    assert outcome.ok and outcome.verdicts[0].message == "posted!"
    assert outcome.verdicts[0].kind == "human"


def test_human_without_store_fails(tmp_path: Path) -> None:
    """No AskStore means a failing verdict, not a crash."""
    outcome = _run(tmp_path, [Check(name="gate", kind="human", prompt="Post?")])
    assert not outcome.ok and outcome.verdicts[0].message == "no question store"


async def _stub_coder(check: Check, ctx: Mapping[str, Any]) -> Verdict:
    """A stub CoderCheckRunner judging from ctx."""
    assert ctx["outputs"]["fine"] is True
    return Verdict(name=check.name, ok=True, message="judged", kind="coder")


def test_coder_check_delegates(tmp_path: Path) -> None:
    """A stub runner's verdict is recorded; None runner fails the check."""
    check = Check(name="review", kind="coder", prompt="Is it fine?")
    outcome = _run(tmp_path, [check], {"outputs": {"fine": True}}, run_coder_check=_stub_coder)
    assert outcome.ok and outcome.verdicts[0].message == "judged"
    assert read_verdict(verdict_file(_attempt(tmp_path), "review")) == outcome.verdicts[0]
    outcome = _run(tmp_path, [check], {"outputs": {"fine": True}})
    assert not outcome.ok and outcome.verdicts[0].message == "coder checks unavailable"


def test_template_error_is_failing_verdict(tmp_path: Path) -> None:
    """Bad templates fail the check instead of raising."""
    tool = _text_tool("lint", "print('ran')")
    checks = [
        Check(name="broken", tool="lint", args={"word": "{{ missing.deep }}"}),
        Check(name="lint", tool="lint"),
    ]
    outcome = _run(tmp_path, checks, tools=_catalog(tool))
    assert not outcome.ok and outcome.failed is not None and outcome.failed.name == "broken"
    assert "cannot render template" in outcome.verdicts[0].message
    assert [v.name for v in outcome.verdicts] == ["broken"]


def test_verdict_files_roundtrip(tmp_path: Path) -> None:
    """write_verdict/read_verdict keep every field; bad files read as None."""
    attempt = _attempt(tmp_path)
    verdict = Verdict(
        name="lint", ok=False, message="oops", outputs={"n": 1}, duration_s=0.5, kind="tool"
    )
    assert write_verdict(attempt, verdict) == attempt / "checks" / "lint.json"
    assert read_verdict(attempt / "checks" / "lint.json") == verdict
    assert read_verdict(attempt / "checks" / "absent.json") is None
    broken = attempt / "checks" / "broken.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("not json{", encoding="utf-8")
    assert read_verdict(broken) is None
    assert json.loads((attempt / "checks" / "lint.json").read_text(encoding="utf-8"))["ok"] is False


def test_decide_every_on_fail() -> None:
    """pass when ok; else on_fail, with retry spent once attempt > retries."""
    passing = CheckOutcome(verdicts=(Verdict(name="a", ok=True, message=""),), failed=None)
    assert decide(passing, attempt=9, retries=1) == "pass"
    for on_fail, fate in [("fail", "fail"), ("skip", "skip"), ("stop", "stop")]:
        failed = CheckOutcome(
            verdicts=(Verdict(name="a", ok=False, message="m"),),
            failed=Check(name="a", on_fail=on_fail),
        )
        assert decide(failed, attempt=1, retries=3) == fate
    retrying = CheckOutcome(
        verdicts=(Verdict(name="a", ok=False, message="m"),),
        failed=Check(name="a", on_fail="retry"),
    )
    assert decide(retrying, attempt=1, retries=3) == "retry"
    assert decide(retrying, attempt=3, retries=3) == "retry"
    assert decide(retrying, attempt=4, retries=3) == "fail"


def test_retry_feedback() -> None:
    """The next attempt's prompt section names the check and its message."""
    assert retry_feedback(Verdict(name="lint", ok=False, message="oops")) == (
        "# Previous attempt failed check `lint`\n\noops\n"
    )
