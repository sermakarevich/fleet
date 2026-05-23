import os
import tempfile
import tomllib
from dataclasses import fields
from pathlib import Path

from fleet.schemas import RuntimeConfig

_KEY_TYPES: dict[str, type] = {
    "max_concurrent": int,
    "rate_limit_threshold_pct": int,
    "retry_limit": int,
    "config_poll_interval_sec": int,
    "claim_poll_interval_sec": int,
    "shutdown_grace_sec": int,
    "rate_limit_default_sleep_sec": int,
    "status_log_interval_sec": int,
    "log_root": str,
    "model": str,
    "coder": str,
}

_TOML_HEADER_PATH = Path(__file__).parent / "templates" / "runtime.toml.header"


def _defaults() -> dict:
    cfg = RuntimeConfig()
    return {f.name: getattr(cfg, f.name) for f in fields(cfg)}


def _write_toml_str(data: dict) -> str:
    """Serialize a flat dict of int/str values to TOML."""
    lines = [_TOML_HEADER_PATH.read_text(encoding="utf-8")]
    for k, v in data.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        else:
            lines.append(f"{k} = {v}")
    return "\n".join(lines) + "\n"


def _parse(data: dict) -> RuntimeConfig:
    """Overlay TOML data onto defaults; ignore unknown keys."""
    merged = _defaults()
    for k, v in data.items():
        if k in _KEY_TYPES:
            merged[k] = _KEY_TYPES[k](v)
    return RuntimeConfig(**merged)


def load(path: Path) -> RuntimeConfig:
    """Read + parse runtime.toml; create with defaults when missing."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        defaults = _defaults()
        path.write_text(_write_toml_str(defaults), encoding="utf-8")
        return RuntimeConfig()
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return _parse(data)


def reload_if_changed(
    path: Path, current_mtime: float | None
) -> tuple[RuntimeConfig, float] | None:
    """Return (new_config, new_mtime) if file changed, else None."""
    path = Path(path)
    stat = os.stat(path)
    if current_mtime is not None and stat.st_mtime == current_mtime:
        return None
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return _parse(data), stat.st_mtime


def write_atomic(path: Path, updates: dict[str, str]) -> RuntimeConfig:
    """Merge updates into on-disk TOML atomically; return new RuntimeConfig."""
    path = Path(path)
    unknown = set(updates) - set(_KEY_TYPES)
    if unknown:
        raise ValueError(f"Unknown config key(s): {', '.join(sorted(unknown))}")

    # Validate config_poll_interval_sec constraint (FR-25)
    if "config_poll_interval_sec" in updates:
        val = int(updates["config_poll_interval_sec"])
        if val > 10:
            raise ValueError(
                f"config_poll_interval_sec must be ≤ 10 (got {val})"
            )

    # Load existing or start from defaults
    if path.exists():
        with path.open("rb") as fh:
            existing = tomllib.load(fh)
    else:
        existing = {}

    merged = _defaults()
    merged.update({k: _KEY_TYPES[k](v) for k, v in existing.items() if k in _KEY_TYPES})
    merged.update({k: _KEY_TYPES[k](v) for k, v in updates.items()})

    toml_str = _write_toml_str(merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(toml_str)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return RuntimeConfig(**merged)
