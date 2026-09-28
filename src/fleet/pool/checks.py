"""Run one step's check list and record verdicts (DESIGN.md §3.8).

Checks run in list order after ``reap`` and before the step run is marked
finished. Every verdict is written to ``<attempt_dir>/checks/<name>.json``
before the next check runs; the first failure stops the list. The failed
check's ``on_fail`` decides the step run's fate via :func:`decide`.

Knows nothing about flows or runs as a whole. The two verdict-path helpers
are private duplicates of ``runs.run_dir`` (layering: pool never imports
runs).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from fleet.core.errors import TemplateError
from fleet.flows.model import Check
from fleet.flows.templates import render, render_bool, render_mapping
from fleet.flows.tools import Tool
from fleet.pool.human_run import AskStore, ask_human, is_yes
from fleet.pool.tool_run import run_tool

Fate = Literal["pass", "retry", "fail", "skip", "stop"]
"""What a step run does next after its checks ran."""

CoderCheckRunner = Callable[[Check, Mapping[str, Any]], Awaitable["Verdict"]]
"""Runs one coder check over the template context; owned by the pool caller."""


@dataclass(frozen=True)
class Verdict:
    """One check's answer: pass/fail plus the message for the next attempt."""

    name: str
    ok: bool
    message: str
    outputs: Any = None  # parsed JSON object from a tool check, else None
    duration_s: float = 0.0
    kind: str = "tool"


@dataclass(frozen=True)
class CheckOutcome:
    """Every verdict in run order plus the first failing check, if any."""

    verdicts: tuple[Verdict, ...]
    failed: Check | None  # first failing check, or None

    @property
    def ok(self) -> bool:
        """True when no check failed."""
        return self.failed is None


def _checks_dir(attempt_dir: Path) -> Path:
    """The verdict folder of one attempt (``attempt_dir / "checks"``)."""
    return attempt_dir / "checks"


def _check_path(attempt_dir: Path, name: str) -> Path:
    """The verdict file of one check (``checks dir / "<name>.json"``)."""
    return _checks_dir(attempt_dir) / f"{name}.json"


def verdict_file(attempt_dir: Path, name: str) -> Path:
    """The verdict file of one check (``<attempt_dir>/checks/<name>.json``)."""
    return _check_path(attempt_dir, name)


def write_verdict(attempt_dir: Path, verdict: Verdict) -> Path:
    """Write ``verdict`` to its file, creating the checks dir; return the path."""
    path = _check_path(attempt_dir, verdict.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "name": verdict.name,
                "ok": verdict.ok,
                "message": verdict.message,
                "outputs": verdict.outputs,
                "duration_s": verdict.duration_s,
                "kind": verdict.kind,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def read_verdict(path: Path) -> Verdict | None:
    """Read one verdict file; None when missing, unreadable, or not an object."""
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    name = decoded.get("name")
    return Verdict(
        name=name if isinstance(name, str) and name else path.stem,
        ok=bool(decoded.get("ok", False)),
        message=str(decoded.get("message", "")),
        outputs=decoded.get("outputs"),
        duration_s=float(decoded.get("duration_s", 0.0) or 0.0),
        kind=str(decoded.get("kind", "tool") or "tool"),
    )


def _is_unknown_tool(exc: Exception) -> bool:
    """True when ``exc`` means the catalog has no such tool."""
    return isinstance(exc, KeyError) or type(exc).__name__ == "ToolNotFound"


def _tool_message(stdout: str, stderr: str, output: Any) -> tuple[str, Any]:
    """Pick a tool verdict's (message, outputs) with json > stdout > stderr."""
    if isinstance(output, dict):
        raw_message = output.get("message")
        if raw_message is not None and str(raw_message).strip():
            return str(raw_message), output
        return stdout.strip() or stderr.strip(), output
    return stdout.strip() or stderr.strip(), None


async def _run_tool_check(
    check: Check,
    ctx: Mapping[str, Any],
    *,
    tools: Callable[[str], Tool],
    cwd: Path,
    attempt_dir: Path,
    environ: Mapping[str, str],
) -> Verdict:
    """Render args, run the tool, and convert its result into a verdict."""
    try:
        tool = tools(check.tool or "")
    except Exception as exc:
        if _is_unknown_tool(exc):
            return Verdict(name=check.name, ok=False, message=f"unknown tool {check.tool}")
        raise
    args = render_mapping(check.args, ctx)
    result = await run_tool(
        tool,
        args,
        cwd=cwd,
        attempt_dir=_checks_dir(attempt_dir) / check.name,
        environ=environ,
    )
    message, outputs = _tool_message(result.stdout, result.stderr, result.output)
    return Verdict(
        name=check.name,
        ok=result.ok,
        message=message,
        outputs=outputs,
        duration_s=result.duration_s,
    )


async def _run_human_check(
    check: Check,
    ctx: Mapping[str, Any],
    *,
    ask_store: AskStore | None,
    task_id: str,
    attempt_dir: Path,
) -> Verdict:
    """Ask one yes/no question; yes passes, the note (else answer) is the message."""
    if ask_store is None:
        return Verdict(name=check.name, ok=False, message="no question store", kind="human")
    start = time.monotonic()
    answer = await ask_human(
        ask_store,
        render(check.prompt, ctx),
        task_id=task_id,
        context=f"check:{check.name}:{attempt_dir.name}",
        options=["yes", "no"],
    )
    return Verdict(
        name=check.name,
        ok=is_yes(answer),
        message=answer.note or answer.answer,
        duration_s=time.monotonic() - start,
        kind="human",
    )


async def run_checks(  # noqa: PLR0913
    checks: Sequence[Check],
    ctx: Mapping[str, Any],  # template context; contains "outputs" for `after`
    *,
    when: str,  # "before" | "after": only checks with this `when` run
    tools: Callable[[str], Tool],  # catalog.tool; raises KeyError/ToolNotFound when unknown
    cwd: Path,
    attempt_dir: Path,
    environ: Mapping[str, str],
    ask_store: AskStore | None,  # pool.human_run.AskStore
    task_id: str,  # for human questions: "<run_id>.<step>[.<index>]"
    run_coder_check: CoderCheckRunner | None,
) -> CheckOutcome:
    """Run one step's checks for one hook point, recording every verdict.

    Checks with a different ``when`` are skipped silently; a check whose
    ``skip_if`` renders true is recorded as passed with ``"skipped"``. The
    first failure stops the list. A ``TemplateError`` while rendering a
    check becomes a failing verdict, never an exception.
    """
    verdicts: list[Verdict] = []
    failed: Check | None = None
    for check in checks:
        if check.when != when:
            continue
        try:
            if check.skip_if is not None and render_bool(check.skip_if, ctx):
                verdict = Verdict(name=check.name, ok=True, message="skipped", kind=check.kind)
            elif check.kind == "tool":
                verdict = await _run_tool_check(
                    check, ctx, tools=tools, cwd=cwd, attempt_dir=attempt_dir, environ=environ
                )
            elif check.kind == "human":
                verdict = await _run_human_check(
                    check, ctx, ask_store=ask_store, task_id=task_id, attempt_dir=attempt_dir
                )
            elif run_coder_check is None:
                verdict = Verdict(
                    name=check.name, ok=False, message="coder checks unavailable", kind="coder"
                )
            else:
                verdict = await run_coder_check(check, ctx)
        except TemplateError as exc:
            verdict = Verdict(name=check.name, ok=False, message=str(exc), kind=check.kind)
        write_verdict(attempt_dir, verdict)
        verdicts.append(verdict)
        if not verdict.ok:
            failed = check
            break
    return CheckOutcome(verdicts=tuple(verdicts), failed=failed)


def decide(outcome: CheckOutcome, *, attempt: int, retries: int) -> Fate:
    """Map an outcome to a fate: pass when ok, else the failed on_fail.

    A ``retry`` becomes ``fail`` once ``attempt`` exceeds ``retries``.
    """
    if outcome.ok or outcome.failed is None:
        return "pass"
    on_fail = cast(Fate, outcome.failed.on_fail)
    if on_fail == "retry" and attempt > retries:
        return "fail"
    return on_fail


def retry_feedback(verdict: Verdict) -> str:
    """The prompt section for the next attempt after ``verdict`` failed."""
    return f"# Previous attempt failed check `{verdict.name}`\n\n{verdict.message}\n"
