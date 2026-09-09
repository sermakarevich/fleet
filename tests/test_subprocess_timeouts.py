"""Every `subprocess.run` call carries a timeout (ADR 0006 bead 22).

A call that could hang forever must fail fast: this test walks the AST of
every module under src/fleet and fails on a `subprocess.run` (or
check_output/call) without an explicit `timeout=` keyword. `subprocess.Popen`
is exempt — a detached spawn takes no timeout parameter (see
observability/daemon.py::start); `asyncio.create_subprocess_exec` is exempt —
it is awaited through `asyncio.wait_for` at the call site.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "fleet"

_TIMEOUTED_CALLS = {"run", "call", "check_output", "check_call"}


def _run_without_timeout(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
            and func.attr in _TIMEOUTED_CALLS
        ):
            keywords = {kw.arg for kw in node.keywords}
            if "timeout" not in keywords:
                problems.append(f"{path}:{node.lineno} subprocess.{func.attr}() without timeout=")
    return problems


def test_every_subprocess_run_has_timeout() -> None:
    """No subprocess.run/call/check_output in src/fleet may hang forever."""
    problems: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        problems.extend(_run_without_timeout(path))
    assert not problems, "subprocess calls without timeout=:\n" + "\n".join(problems)
