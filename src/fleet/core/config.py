"""Runtime configuration: pure parse/render of runtime.toml data.

This module never touches the disk. File I/O (load, reload_if_changed,
write) lives in ``state/config_file.py``; this module owns the
``RuntimeConfig`` type plus the pure ``parse`` (dict -> config) and
``render_toml`` (dict -> TOML text) helpers it is built from.
"""

import logging
from dataclasses import dataclass, fields
from pathlib import Path

from fleet.core.errors import ConfigError

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
    state_max_bytes: int = 6144
    compaction_enabled: bool = True
    compaction_coder: str = "claude"
    compaction_model: str = "haiku"
    context_checkpoint_pct: int = 75
    context_kill_pct: int = 90
    isolation: str = "worktree"
    isolation_exclude: str = ""
    post_merge_command: str = ""
    triage_interval_minutes: int = 15
    gc_retention_days: int = 30
    gc_archive_days: int = 90
    # Observer worker: max follow-up beads opened per validation round, and
    # max partial observer rounds before the epic blocks for human review.
    observer_max_followups: int = 10
    observer_max_rounds: int = 3
    # Job worker: human gate on/off, child defaults, caps per phase/table.
    job_gate: bool = True
    job_child_coder: str = "claude"
    job_child_model: str = "sonnet"
    job_max_children: int = 30
    job_max_phase_attempts: int = 2


_KEY_TYPES: dict[str, type] = {
    f.name: f.type  # type: ignore[misc]
    for f in fields(RuntimeConfig())
}

_TOML_HEADER_PATH = Path(__file__).parent.parent / "templates" / "runtime.toml.header"


def _defaults() -> dict:
    config = RuntimeConfig()
    return {f.name: getattr(config, f.name) for f in fields(config) if f.name in _KEY_TYPES}


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
            raise ConfigError(f"Invalid bool for {key}: {value!r}")
        return bool(value)
    return typ(value)


def render_toml(data: dict) -> str:
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
_DEPRECATED_CONTEXT_KEYS = frozenset({"opencode_context_limit", "opencode_bedrock_context_limit"})


def _warn_deprecated(data: dict) -> None:
    found = sorted(_DEPRECATED_CONTEXT_KEYS & set(data))
    if found:
        logger.warning(
            "Deprecated runtime.toml key(s) %s ignored; use "
            'context_windows="model:tokens,model:tokens" instead.',
            ", ".join(found),
        )


def _validate_isolation(value: object) -> None:
    """Raise ConfigError when `isolation` is not a known mode."""
    if value not in ("worktree", "none"):
        raise ConfigError(f"Invalid isolation mode {value!r}: expected 'worktree' or 'none'")


def parse(data: dict) -> RuntimeConfig:
    """Overlay TOML data onto defaults; ignore unknown keys."""
    _warn_deprecated(data)
    merged = _defaults()
    for k, v in data.items():
        if k in _KEY_TYPES:
            merged[k] = _coerce(k, v)
    _validate_isolation(merged.get("isolation"))
    return RuntimeConfig(**merged)


def merge(existing: dict, updates: dict) -> dict:
    """Merge on-disk TOML data and new updates onto defaults; all coerced."""
    unknown = set(updates) - set(_KEY_TYPES)
    if unknown:
        raise ConfigError(f"Unknown config key(s): {', '.join(sorted(unknown))}")
    if "isolation" in updates:
        _validate_isolation(_coerce("isolation", updates["isolation"]))
    merged = _defaults()
    merged.update({k: _coerce(k, v) for k, v in existing.items() if k in _KEY_TYPES})
    merged.update({k: _coerce(k, v) for k, v in updates.items()})
    return merged
