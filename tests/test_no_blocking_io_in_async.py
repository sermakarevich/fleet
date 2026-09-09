"""No blocking I/O directly inside `async def` (ADR 0006 bead 22).

Async handlers in serve/ and integrations/ must never call blocking file,
subprocess, socket, or sqlite primitives on the event-loop thread: the read
runs in a sync helper via `await asyncio.to_thread(...)` (the rule written
in serve/api/__init__.py). This test walks the AST of every module under
src/fleet/serve and src/fleet/integrations and fails on a bare primitive
call inside an `async def` that is not nested under a `to_thread(...)` call.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [REPO_ROOT / "src" / "fleet" / "serve", REPO_ROOT / "src" / "fleet" / "integrations"]

#: Attribute calls that block the loop (Path.read_text, urlopen, Path.open...).
_BLOCKING_ATTRS = {"read_text", "write_text", "read_bytes", "open", "urlopen"}
#: subprocess.* spawns that block the loop.
_SUBPROCESS_CALLS = {"run", "Popen", "call", "check_output", "check_call"}
#: sqlite3 entry points that hit the disk.
_SQLITE_CALLS = {"connect", "execute", "executemany", "executescript"}


def _is_blocking(call: ast.Call) -> str | None:
    """Reason the call blocks, or None when it is loop-safe."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "open":
        return "open()"
    if isinstance(func, ast.Attribute):
        if func.attr in _BLOCKING_ATTRS:
            return f".{func.attr}()"
        value = func.value
        if isinstance(value, ast.Name):
            if value.id == "subprocess" and func.attr in _SUBPROCESS_CALLS:
                return f"subprocess.{func.attr}()"
            if value.id == "sqlite3" and func.attr in _SQLITE_CALLS:
                return f"sqlite3.{func.attr}()"
    return None


class _AsyncBlockingVisitor(ast.NodeVisitor):
    """Collect bare blocking calls inside `async def` (not under to_thread)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.problems: list[str] = []
        self._async_depth = 0
        self._to_thread_depth = 0

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._async_depth += 1
        self.generic_visit(node)
        self._async_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        is_to_thread = isinstance(func, ast.Attribute) and func.attr == "to_thread"
        if is_to_thread:
            self._to_thread_depth += 1
            self.generic_visit(node)
            self._to_thread_depth -= 1
            return
        if self._async_depth > 0 and self._to_thread_depth == 0:
            reason = _is_blocking(node)
            if reason is not None:
                self.problems.append(f"{self.path}:{node.lineno} {reason} in async def")
        self.generic_visit(node)


def _problems_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    visitor = _AsyncBlockingVisitor(path)
    visitor.visit(tree)
    return visitor.problems


def test_no_blocking_io_directly_in_async() -> None:
    """Every blocking primitive in serve/integrations sits under to_thread."""
    problems: list[str] = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            problems.extend(_problems_in(path))
    assert not problems, "blocking I/O on the event loop:\n" + "\n".join(problems)
