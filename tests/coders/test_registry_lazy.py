"""Lazy coder registry: importing the package imports no coder module."""

import subprocess
import sys
from pathlib import Path

import pytest

from fleet.coders import REGISTRY, resolve_coder

_IMPL_MODULES = (
    "fleet.coders.agy",
    "fleet.coders.claude",
    "fleet.coders.codex",
    "fleet.coders.opencode",
    "fleet.coders.pi",
)

_CHECK_SCRIPT = (
    "import sys; "
    "import fleet.coders; "
    "loaded = sorted(m for m in sys.modules if m.startswith('fleet.coders.')); "
    "print(','.join(loaded))"
)


def _fresh_import_coder_modules() -> list[str]:
    """Coder submodules loaded by a fresh `import fleet.coders` (subprocess)."""
    proc = subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip().split(",") if proc.stdout.strip() else []


def test_package_import_does_not_import_pi():
    assert "fleet.coders.pi" not in _fresh_import_coder_modules()


def test_package_import_does_not_import_any_coder_impl():
    loaded = _fresh_import_coder_modules()
    for module in _IMPL_MODULES:
        assert module not in loaded


def test_resolve_coder_builds_every_registered_coder(tmp_path: Path):
    for name in REGISTRY:
        coder = resolve_coder(name, model=None, fleet_home=tmp_path)
        assert coder.spec.name == name


def test_resolve_coder_unknown_name_raises():
    with pytest.raises(ValueError, match="Unknown coder"):
        resolve_coder("no-such-coder", model=None, fleet_home=Path("/tmp"))
