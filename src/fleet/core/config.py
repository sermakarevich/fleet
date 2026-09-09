"""Runtime configuration: pure parse/render of runtime.toml data.

This module never touches the disk. File I/O (load, reload_if_changed,
write) lives in ``state/config_file.py``; this module owns the
``RuntimeConfig`` type plus the pure ``parse`` (dict -> config) and
``render_toml`` (dict -> TOML text) helpers it is built from.

Every field carries ``metadata={"doc": ..., "example": ...}``: the one-line
user doc and an example value. ``render_settings_table`` and
``render_toml_header`` turn that metadata into ``docs/CONFIG.md`` and
``templates/runtime.toml.header`` (via ``fleet config docs --write``).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path

from fleet.core.errors import ConfigError

logger = logging.getLogger(__name__)


def _meta(doc: str, example: str) -> dict[str, str]:
    """Field metadata: one-line user doc plus an example value."""
    return {"doc": doc, "example": example}


@dataclass
class RuntimeConfig:
    max_concurrent: int = field(
        default=3,
        metadata=_meta("Maximum agent subprocesses running at once.", "5"),
    )
    model: str = field(
        default="sonnet",
        metadata=_meta("Default model when a task sets no override.", "opus"),
    )
    coder: str = field(
        default="claude",
        metadata=_meta("Default coder CLI when a task sets no override.", "codex"),
    )
    telegram_chat_id: str = field(
        default="",
        metadata=_meta(
            "Telegram chat ID for notifications; empty disables them.",
            "-1001234567890",
        ),
    )
    telegram_allowed_ids: str = field(
        default="",
        metadata=_meta(
            "Telegram sender IDs allowed inbound commands; empty disables all.",
            "123456789,987654321",
        ),
    )
    telegram_default_cwd: str = field(
        default="",
        metadata=_meta(
            "Working directory for tasks created via Telegram; empty leaves unset.",
            "/Users/you/git/myproject",
        ),
    )
    opencode_ollama_url: str = field(
        default="http://127.0.0.1:11435/v1",
        metadata=_meta(
            "Ollama API base URL used by the opencode coder.",
            "http://127.0.0.1:11434/v1",
        ),
    )
    ollama_ssh_host: str = field(
        default="rtx",
        metadata=_meta(
            "SSH host alias for the GPU box behind opencode_ollama_url.",
            "gpubox",
        ),
    )
    ollama_remote_port: int = field(
        default=11434,
        metadata=_meta(
            "Ollama port on the GPU box (remote end of the tunnel).",
            "11434",
        ),
    )
    max_concurrent_overrides: str = field(
        default="",
        metadata=_meta(
            "Per-coder limits as coder:limit pairs; others use max_concurrent.",
            "claude:2,opencode:4",
        ),
    )
    context_windows: str = field(
        default="",
        metadata=_meta(
            "Per-model context windows as model:tokens pairs; empty uses built-ins.",
            "muse-spark-1.3-contributor:1048576",
        ),
    )
    opencode_default_model: str = field(
        default="qwen3.6:latest",
        metadata=_meta(
            "Ollama model for opencode tasks without an override.",
            "qwen3.5:27b",
        ),
    )
    opencode_bedrock_region: str = field(
        default="",
        metadata=_meta(
            "AWS region for Bedrock; empty inherits the environment.",
            "us-east-1",
        ),
    )
    opencode_bedrock_profile: str = field(
        default="",
        metadata=_meta(
            "AWS profile for Bedrock; empty inherits the environment.",
            "dev",
        ),
    )
    stall_warning_minutes: int = field(
        default=15,
        metadata=_meta(
            "Silence minutes before an attempt counts as stalled.",
            "30",
        ),
    )
    stall_action: str = field(
        default="kill",
        metadata=_meta(
            "Stall response: warn logs only, kill stops the attempt.",
            "warn",
        ),
    )
    max_attempt_minutes: int = field(
        default=120,
        metadata=_meta(
            "Wall-clock cap per attempt; 0 disables. Over budget kills.",
            "60",
        ),
    )
    continue_pack_max_bytes: int = field(
        default=8192,
        metadata=_meta(
            "Pack budget in bytes before a continue launch compacts.",
            "16384",
        ),
    )
    state_max_bytes: int = field(
        default=6144,
        metadata=_meta(
            "Hard cap on the worker-memory file STATE.md in bytes.",
            "8192",
        ),
    )
    compaction_enabled: bool = field(
        default=True,
        metadata=_meta(
            "Compact before continue launches that need it; else truncate.",
            "false",
        ),
    )
    compaction_coder: str = field(
        default="claude",
        metadata=_meta("Coder CLI used for the cheap compaction call.", "claude"),
    )
    compaction_model: str = field(
        default="haiku",
        metadata=_meta("Model used for the cheap compaction call.", "haiku"),
    )
    context_checkpoint_pct: int = field(
        default=75,
        metadata=_meta(
            "Peak-context percent that asks the model to wrap up early.",
            "80",
        ),
    )
    context_kill_pct: int = field(
        default=90,
        metadata=_meta(
            "Peak-context percent that kills with CONTEXT_PRESSURE.",
            "95",
        ),
    )
    isolation: str = field(
        default="worktree",
        metadata=_meta(
            "Git worktree isolation: worktree isolates repo tasks, none runs in place.",
            "none",
        ),
    )
    isolation_exclude: str = field(
        default="",
        metadata=_meta(
            "Repo roots that never get a worktree; empty excludes none.",
            "/Users/me/.ai",
        ),
    )
    post_merge_command: str = field(
        default="",
        metadata=_meta(
            "Shell command after a clean worktree merge; empty skips.",
            "make ui-build",
        ),
    )
    triage_interval_minutes: int = field(
        default=15,
        metadata=_meta(
            "Minutes between blocked-task triage scans; 0 disables.",
            "30",
        ),
    )
    gc_retention_days: int = field(
        default=30,
        metadata=_meta(
            "Days before closed tasks archive; 0 disables archiving.",
            "7",
        ),
    )
    gc_archive_days: int = field(
        default=90,
        metadata=_meta(
            "Days before archives delete permanently; 0 disables purging.",
            "30",
        ),
    )
    # Observer worker: max follow-up tasks opened per validation round, and
    # max partial observer rounds before the epic blocks for human review.
    observer_max_followups: int = field(
        default=10,
        metadata=_meta(
            "Max follow-up tasks opened per observer validation round.",
            "5",
        ),
    )
    observer_max_rounds: int = field(
        default=3,
        metadata=_meta(
            "Max partial observer rounds before human review.",
            "5",
        ),
    )
    # Job worker: human gate on/off, child defaults, caps per phase/table.
    job_gate: bool = field(
        default=True,
        metadata=_meta(
            "Ask approval before a job spawns its planned children.",
            "false",
        ),
    )
    job_child_coder: str = field(
        default="claude",
        metadata=_meta("Default coder for job-spawned child tasks.", "opencode"),
    )
    job_child_model: str = field(
        default="sonnet",
        metadata=_meta("Default model for job-spawned child tasks.", "opus"),
    )
    job_max_children: int = field(
        default=30,
        metadata=_meta("Max children one job phase may spawn.", "10"),
    )
    job_max_phase_attempts: int = field(
        default=2,
        metadata=_meta(
            "Max research/design attempts before a job blocks.",
            "3",
        ),
    )
    # Serve CORS: browser origins allowed to call the API cross-origin.
    # Empty (default) means same-origin only (no CORS headers are sent).
    serve_cors_origins: list[str] = field(
        default_factory=list,
        metadata=_meta(
            "Browser origins allowed cross-origin; empty is same-origin only.",
            "https://fleet.example.com",
        ),
    )
    # UI server bind address and port (`fleet serve start --host/--port`
    # default to these). 0.0.0.0 exposes the UI on the LAN/Tailscale, so
    # pair it with FLEET_API_TOKEN (see README "Network exposure"); use
    # 127.0.0.1 for local-only.
    serve_host: str = field(
        default="0.0.0.0",
        metadata=_meta(
            "UI server bind address; 0.0.0.0 exposes LAN, 127.0.0.1 local only.",
            "127.0.0.1",
        ),
    )
    serve_port: int = field(
        default=7890,
        metadata=_meta("UI server port.", "8080"),
    )


@dataclass(frozen=True, slots=True)
class SettingRow:
    """One documented setting: name, type, default, doc, example."""

    name: str
    kind: str
    default: str
    doc: str
    example: str


_KEY_TYPES: dict[str, type] = {
    f.name: f.type  # type: ignore[misc]
    for f in fields(RuntimeConfig())
}

_TOML_HEADER_PATH = Path(__file__).parent.parent / "templates" / "runtime.toml.header"

_HEADER_PREAMBLE = """# Runtime configuration for the fleet supervisor.
# Edit via `fleet config set <key>=<value>`. The supervisor re-reads this
# file periodically and applies changes without restart.
# In-flight subprocesses are NEVER killed by a config change.
#
# Full reference with defaults: docs/CONFIG.md (generated from the same
# metadata by `fleet config docs --write`; do not edit this header by hand).
#"""


def defaults() -> dict:
    config = RuntimeConfig()
    return {f.name: getattr(config, f.name) for f in fields(config) if f.name in _KEY_TYPES}


def _type_name(typ: object) -> str:
    """Short type label for the docs table (bool/int/str/list[str])."""
    if typ is bool or typ is int or typ is str:
        return typ.__name__
    if typ is list or getattr(typ, "__origin__", None) is list:
        return "list[str]"
    return str(typ)


def _format_value(value: object) -> str:
    """One TOML value: bools lowercase, lists quoted arrays, strings quoted."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(f'"{item}"' for item in value) + "]"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def setting_rows() -> list[SettingRow]:
    """Every RuntimeConfig field as a doc row, in definition order."""
    config = RuntimeConfig()
    rows = []
    for f in fields(config):
        meta = f.metadata
        rows.append(
            SettingRow(
                name=f.name,
                kind=_type_name(f.type),
                default=_format_value(getattr(config, f.name)),
                doc=str(meta.get("doc", "")),
                example=str(meta.get("example", "")),
            )
        )
    return rows


def render_settings_table() -> str:
    """Settings rows as a Markdown table (docs/CONFIG.md region)."""
    lines = ["| Name | Type | Default | Description | Example |", "|---|---|---|---|---|"]
    for row in setting_rows():
        lines.append(
            f"| `{row.name}` | `{row.kind}` | `{row.default}` | "
            f"{row.doc} | `fleet config set {row.name}={row.example}` |"
        )
    return "\n".join(lines) + "\n"


def render_toml_header() -> str:
    """runtime.toml.header text generated from the same field metadata."""
    blocks = [_HEADER_PREAMBLE]
    for row in setting_rows():
        blocks.append(
            f"#\n# {row.name}: {row.doc}\n"
            f"#   Default {row.default}; "
            f"e.g. fleet config set {row.name}={row.example}"
        )
    return "\n".join(blocks) + "\n"


def _coerce_bool(key: str, value: object) -> object:
    """Bool field: bools pass through, strings accept true/false words."""
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


def _coerce_list(key: str, value: object) -> list[str]:
    """List field: TOML arrays pass through, cli strings split on commas."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ConfigError(f"Invalid list for {key}: {value!r}")


def coerce(key: str, value: object) -> object:
    """Coerce a TOML/cli value to the field's type; bool and lists accept strings."""
    typ = _KEY_TYPES[key]
    if typ is bool:
        return _coerce_bool(key, value)
    if typ is list or getattr(typ, "__origin__", None) is list:
        return _coerce_list(key, value)
    return typ(value)


def render_toml(data: dict) -> str:
    """Serialize a flat dict of int/str/bool values to TOML."""
    lines = [_TOML_HEADER_PATH.read_text(encoding="utf-8").rstrip("\n")]
    for k, v in data.items():
        lines.append(f"{k} = {_format_value(v)}")
    return "\n".join(lines) + "\n"


# Removed keys, kept only to warn on migration: use `context_windows`
# ("model:tokens,model:tokens", e.g. "muse-spark-1.3-contributor:1048576")
# instead of one global number per backend. `stall_block_after` was removed
# outright in Clean 30/30: nothing ever read it (the stall block threshold
# is the STALL_MAX_ROUNDS constant in core/limits.py), so an unknown
# `stall_block_after` line in an old runtime.toml is now ignored.
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
    merged = defaults()
    for k, v in data.items():
        if k in _KEY_TYPES:
            merged[k] = coerce(k, v)
    _validate_isolation(merged.get("isolation"))
    return RuntimeConfig(**merged)


def merge(existing: Mapping[str, object], updates: Mapping[str, object]) -> dict:
    """Merge on-disk TOML data and new updates onto defaults; all coerced."""
    unknown = set(updates) - set(_KEY_TYPES)
    if unknown:
        raise ConfigError(f"Unknown config key(s): {', '.join(sorted(unknown))}")
    if "isolation" in updates:
        _validate_isolation(coerce("isolation", updates["isolation"]))
    merged = defaults()
    merged.update({k: coerce(k, v) for k, v in existing.items() if k in _KEY_TYPES})
    merged.update({k: coerce(k, v) for k, v in updates.items()})
    return merged
