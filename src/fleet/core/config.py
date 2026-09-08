import logging
import os
import tempfile
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RuntimeConfig:
    max_concurrent: int = 3
    model: str = "sonnet"
    coder: str = "claude"
    telegram_chat_id: str = ""
    telegram_allowed_ids: str = ""
    telegram_default_cwd: str = ""
    opencode_ollama_url: str = "http://127.0.0.1:11435/v1"
    max_concurrent_overrides: str = ""
    context_windows: str = ""
    opencode_default_model: str = "qwen3.6:latest"
    opencode_bedrock_region: str = ""
    opencode_bedrock_profile: str = ""
    stall_warning_minutes: int = 15
    stall_action: str = "kill"
    stall_block_after: int = 2
    max_attempt_minutes: int = 120
    continue_pack_max_bytes: int = 8192
    handoff_max_bytes: int = 2048
    knowledge_max_bytes: int = 4096
    compaction_enabled: bool = True
    compaction_coder: str = "claude"
    compaction_model: str = "haiku"
    context_checkpoint_pct: int = 75
    context_kill_pct: int = 90
    isolation: str = "worktree"
    post_merge_command: str = ""
    triage_interval_minutes: int = 15
    gc_retention_days: int = 30
    gc_archive_days: int = 90


_KEY_TYPES: dict[str, type] = {
    f.name: f.type  # type: ignore[misc]
    for f in fields(RuntimeConfig())
}

_TOML_HEADER_PATH = Path(__file__).parent.parent / "templates" / "runtime.toml.header"


def _defaults() -> dict:
    cfg = RuntimeConfig()
    return {f.name: getattr(cfg, f.name) for f in fields(cfg) if f.name in _KEY_TYPES}


def _coerce(key: str, value: object) -> object:
    """Coerce a TOML/cli value to the field's type; bool accepts strings."""
    typ = _KEY_TYPES[key]
    if typ is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
            raise ValueError(f"Invalid bool for {key}: {value!r}")
        return bool(value)
    return typ(value)  # type: ignore[operator]


def _write_toml_str(data: dict) -> str:
    """Serialize a flat dict of int/str/bool values to TOML."""
    lines = [_TOML_HEADER_PATH.read_text(encoding="utf-8")]
    for k, v in data.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        else:
            lines.append(f"{k} = {v}")
    return "\n".join(lines) + "\n"


# Removed keys, kept only to warn on migration: use `context_windows`
# ("model:tokens,model:tokens", e.g. "muse-spark-1.3-contributor:1048576")
# instead of one global number per backend.
_DEPRECATED_CONTEXT_KEYS = frozenset(
    {"opencode_context_limit", "opencode_bedrock_context_limit"}
)


def _warn_deprecated(data: dict) -> None:
    found = sorted(_DEPRECATED_CONTEXT_KEYS & set(data))
    if found:
        logger.warning(
            "Deprecated runtime.toml key(s) %s ignored; use "
            "context_windows=\"model:tokens,model:tokens\" instead.",
            ", ".join(found),
        )


def _validate_isolation(value: object) -> None:
    """Raise ValueError when `isolation` is not a known mode."""
    if value not in ("worktree", "none"):
        raise ValueError(
            f"Invalid isolation mode {value!r}: expected 'worktree' or 'none'"
        )


def _parse(data: dict) -> RuntimeConfig:
    """Overlay TOML data onto defaults; ignore unknown keys."""
    _warn_deprecated(data)
    merged = _defaults()
    for k, v in data.items():
        if k in _KEY_TYPES:
            merged[k] = _coerce(k, v)
    _validate_isolation(merged.get("isolation"))
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

    if "coder" in updates:
        # Lazy import: avoid any chance of a circular import with the coders package.
        from fleet.coders import get_coder

        get_coder(updates["coder"])  # raises ValueError on unknown coder name

    if "isolation" in updates:
        _validate_isolation(_coerce("isolation", updates["isolation"]))

    # Load existing or start from defaults
    if path.exists():
        with path.open("rb") as fh:
            existing = tomllib.load(fh)
    else:
        existing = {}

    merged = _defaults()
    merged.update({k: _coerce(k, v) for k, v in existing.items() if k in _KEY_TYPES})
    merged.update({k: _coerce(k, v) for k, v in updates.items()})

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
