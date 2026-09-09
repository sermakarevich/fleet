"""Layer direction test (ADR 0006 rule 4): lower layers never import higher ones.

Walks src/fleet/**/*.py with ast, collects `from fleet.X` / `import fleet.X`
edges, and asserts every edge goes downward through ALLOWED. Adjust ALLOWED
only toward the intended graph in docs/ARCHITECTURE.md — never to bless a
new violation. KNOWN_VIOLATIONS names real violations owned by a later bead;
the test fails on anything not in the set, and fails when a known entry no
longer occurs (so the entry gets removed).
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "fleet"

ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "state": {"core"},
    "beads": {"core", "state"},
    "schedules": {"core", "state", "beads", "workflows"},
    "workflows": {"core", "state", "beads"},
    "coders": {"core", "state"},
    "workers": {"core", "state", "beads", "coders"},
    "orchestrator": {
        "core",
        "state",
        "beads",
        "schedules",
        "workflows",
        "coders",
        "workers",
        "observability",
        "integrations",
    },
    "observability": {"core", "state"},
    # Bead 24: the ollama tunnel (integrations) starts its ssh child through
    # observability/daemon so one pidfile owner tracks it. Same tier, one
    # direction only (observability never imports integrations).
    "integrations": {"core", "state", "beads", "observability"},
    "serve": {
        "core",
        "state",
        "beads",
        "schedules",
        "workflows",
        "coders",
        "workers",
        "orchestrator",
        "observability",
        "integrations",
    },
    "cli": {
        "core",
        "state",
        "beads",
        "schedules",
        "workflows",
        "coders",
        "workers",
        "orchestrator",
        "observability",
        "integrations",
        "serve",
    },
}

KNOWN_VIOLATIONS: set[tuple[str, str]] = {
    ("coders", "integrations"),  # bead 11: mcp_servers placement
}


def _edges() -> dict[tuple[str, str], list[str]]:
    """Map (src_layer, dst_layer) to sorted `file:line` locations."""
    found: dict[tuple[str, str], list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        mod = path.relative_to(SRC).with_suffix("").as_posix().replace("/", ".")
        top = mod.split(".")[0]
        if top not in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    continue  # intra-package relative import
                if not node.module or not node.module.startswith("fleet."):
                    continue
                dst = node.module.split(".")[1]
                if dst == top or dst not in ALLOWED:
                    continue
                found.setdefault((top, dst), []).append(f"{path}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith("fleet."):
                        continue
                    dst = alias.name.split(".")[1]
                    if dst == top or dst not in ALLOWED:
                        continue
                    found.setdefault((top, dst), []).append(f"{path}:{node.lineno}")
    return {k: sorted(v) for k, v in found.items()}


def test_no_new_layer_violations() -> None:
    """Every cross-layer import is allowed or explicitly known."""
    bad = {
        edge: locs
        for edge, locs in _edges().items()
        if edge[1] not in ALLOWED[edge[0]] and edge not in KNOWN_VIOLATIONS
    }
    assert not bad, "layer violations (lower must never import higher): " + "; ".join(
        f"{s}->{d} at {', '.join(locs)}" for (s, d), locs in sorted(bad.items())
    )


def test_known_violations_are_current() -> None:
    """Each KNOWN_VIOLATIONS entry must still occur; remove fixed ones."""
    actual = set(_edges())
    stale = {edge for edge in KNOWN_VIOLATIONS if edge not in actual}
    assert not stale, f"fixed violations still listed in KNOWN_VIOLATIONS: {sorted(stale)}"
