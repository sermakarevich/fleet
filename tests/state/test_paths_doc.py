"""ARCHITECTURE.md's Task directory contract must match `state/paths.py`.

Every filename constant defined in `state/paths.py` has to appear in the
contract block, so the doc and the code cannot drift apart silently.
"""
from __future__ import annotations

from pathlib import Path

import fleet.state.paths as paths

ARCHITECTURE_MD = Path(__file__).resolve().parents[2] / "docs" / "ARCHITECTURE.md"


def _contract_block() -> str:
    text = ARCHITECTURE_MD.read_text(encoding="utf-8")
    start = text.index("## Task directory contract")
    rest = text[start:]
    end = rest.index("\n## ", len("## Task directory contract"))
    return rest[:end]


def test_every_paths_constant_appears_in_contract() -> None:
    block = _contract_block()
    constants = {
        name: value
        for name, value in vars(paths).items()
        if name.isupper() and isinstance(value, str)
    }
    assert constants, "expected filename constants in state/paths.py"
    missing = [f"{n}={v!r}" for n, v in sorted(constants.items()) if v not in block]
    assert not missing, f"constants missing from contract block: {missing}"
