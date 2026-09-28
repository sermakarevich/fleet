"""Execute one tool step run (DESIGN.md §3.7).

Runs a declared tool's rendered argv with ``asyncio.create_subprocess_exec``
(no shell), captures stdout/stderr into the attempt directory, parses stdout
per the tool's declared output kind, and converts the parsed value into step
outputs. Knows nothing about flows or runs as a whole.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fleet.flows.tools import Tool, command_for, missing_env, parse_output, stdin_for


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one tool process execution."""

    exit_code: int | None  # None when refused early or killed by timeout
    stdout: str
    stderr: str
    output: Any  # parse_output(tool, stdout) when exit 0 and parseable, else None
    duration_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        """True when the process exited 0."""
        return self.exit_code == 0


def _write_attempt(attempt_dir: Path, command: list[str], result: ToolResult) -> None:
    """Write stdout.txt, stderr.txt and tool.json into ``attempt_dir``."""
    (attempt_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (attempt_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    (attempt_dir / "tool.json").write_text(
        json.dumps(
            {
                "command": command,
                "exit_code": result.exit_code,
                "duration_s": result.duration_s,
                "timed_out": result.timed_out,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


async def run_tool(
    tool: Tool,
    given: Mapping[str, str],
    *,
    cwd: Path,
    attempt_dir: Path,
    environ: Mapping[str, str],
    timeout_s: float | None = None,
) -> ToolResult:
    """Run ``tool`` with ``given`` args, capturing output into ``attempt_dir``.

    Refuses early (no process) when required env vars are missing;
    otherwise runs ``command_for(tool, given)`` with no shell, a closed
    stdin unless the tool declares one, ``cwd`` and ``env`` as given.
    Always creates ``attempt_dir`` and writes ``stdout.txt``,
    ``stderr.txt`` and ``tool.json`` there. On timeout the process is
    killed and ``timed_out`` is True with ``exit_code`` None. Bad
    ``parse_output`` never raises: ``output`` is None and the reason is
    appended to ``stderr``. Callers decide what a result means.
    """
    attempt_dir.mkdir(parents=True, exist_ok=True)
    missing = missing_env(tool, environ)
    if missing:
        try:
            refused_command = command_for(tool, given)
        except Exception:
            refused_command = []
        refused = ToolResult(
            exit_code=None,
            stdout="",
            stderr="missing env: " + ", ".join(missing),
            output=None,
            duration_s=0.0,
        )
        _write_attempt(attempt_dir, refused_command, refused)
        return refused

    command = command_for(tool, given)
    stdin_text = stdin_for(tool, given)
    timeout = tool.timeout if timeout_s is None else timeout_s

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=dict(environ),
    )
    timed_out = False
    exit_code: int | None
    try:
        raw_out, raw_err = await asyncio.wait_for(
            proc.communicate(stdin_text.encode() if stdin_text is not None else None),
            timeout,
        )
    except TimeoutError:
        timed_out = True
        proc.kill()
        raw_out, raw_err = await proc.communicate()
        exit_code = None
    else:
        exit_code = proc.returncode
    duration_s = time.monotonic() - start

    stdout = raw_out.decode("utf-8", errors="replace") if raw_out else ""
    stderr = raw_err.decode("utf-8", errors="replace") if raw_err else ""
    output: Any = None
    if exit_code == 0:
        try:
            output = parse_output(tool, stdout)
        except Exception as exc:
            reason = f"output: {exc}"
            stderr = f"{stderr}\n{reason}" if stderr else reason
    result = ToolResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        output=output,
        duration_s=duration_s,
        timed_out=timed_out,
    )
    _write_attempt(attempt_dir, command, result)
    return result


def write_step_outputs(step_dir: Path, output: Any) -> Path:
    """Write ``outputs/outputs.json`` in ``step_dir`` from a parsed tool value.

    A dict is written as is; anything else becomes ``{"result": output}``
    (a ``lines`` list, a ``text`` string). Returns the written path.
    """
    path = step_dir / "outputs" / "outputs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = output if isinstance(output, dict) else {"result": output}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
