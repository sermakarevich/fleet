"""Import layering for the orchestrator package (ADR 0005, ADR 0006 bead 18).

Every orchestrator/*.py module may import only lower layers (core, state,
beads, schedules, workflows, workers, coders), sibling orchestrator modules, integrations (the
injected QuestionStore, per docs/ARCHITECTURE.md which allows
orchestrator -> integrations), the stdlib, and third-party packages —
never serve or cli. supervisor.py is the thin runner: it imports no
sibling except service, state, and checks.
"""

from __future__ import annotations

import ast
from pathlib import Path

ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "src" / "fleet" / "orchestrator"
LOWER_LAYERS = {
    "core",
    "state",
    "beads",
    "schedules",
    "workflows",
    "workers",
    "coders",
    "integrations",
}
SUPERVISOR_SIBLINGS = {"service", "state", "checks"}


def _fleet_imports(path: Path) -> tuple[set[str], set[str]]:
    """Return (lower/sibling fleet roots, sibling modules) imported by file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    siblings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    siblings.add(node.module.split(".")[0])
                else:
                    siblings.update(a.name.split(".")[0] for a in node.names)
            elif (node.module or "").startswith("fleet."):
                parts = node.module.split(".")
                roots.add(parts[1] if len(parts) > 1 else "")
                if parts[1] == "orchestrator" and len(parts) > 2:
                    siblings.add(parts[2])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("fleet."):
                    parts = alias.name.split(".")
                    roots.add(parts[1] if len(parts) > 1 else "")
                    if parts[1] == "orchestrator" and len(parts) > 2:
                        siblings.add(parts[2])
    siblings.discard("")
    return roots, siblings


def _orchestrator_modules() -> list[Path]:
    """Every Python module in the orchestrator package."""
    return sorted(p for p in ORCHESTRATOR_DIR.glob("*.py") if p.name != "__init__.py")


def test_orchestrator_imports_only_lower_layers_and_siblings() -> None:
    """No orchestrator module imports serve or cli."""
    allowed = LOWER_LAYERS | {"orchestrator"}
    offenders: dict[str, set[str]] = {}
    for path in _orchestrator_modules():
        roots, _ = _fleet_imports(path)
        bad = {r for r in roots if r not in allowed}
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"higher-layer imports: {offenders}"


def test_supervisor_imports_no_sibling_except_service_state_checks() -> None:
    """supervisor.py stays the thin runner: service, state, checks only."""
    _, siblings = _fleet_imports(ORCHESTRATOR_DIR / "supervisor.py")
    assert siblings <= SUPERVISOR_SIBLINGS, f"extra siblings: {siblings}"


def test_sibling_imports_name_real_modules() -> None:
    """Every sibling import refers to a module file that exists."""
    existing = {p.stem for p in ORCHESTRATOR_DIR.glob("*.py")}
    missing: dict[str, set[str]] = {}
    for path in _orchestrator_modules():
        _, siblings = _fleet_imports(path)
        unknown = {s for s in siblings if s not in existing}
        if unknown:
            missing[path.name] = unknown
    assert not missing, f"sibling imports without a module: {missing}"
