"""Rewriting for `bd create` / `bd new` argv before it is forwarded to `bd`.

`fleet bd create` intercepts `--coder`, `--model`, `--worker`, `--cwd`,
`--isolation` and `--job-gate` instead of forwarding them to `bd` — they
become per-task overrides embedded in `bd`'s own `--metadata`, so they land
atomically with `bd create` before the bead can ever be claimed by the
supervisor. See `queue.py`'s `build_task` for the read side.

This module never validates names against higher layers (beads never
imports coders): the caller (`cli/beads.py`) validates `--coder` before
calling here. Adding a flag means adding one row to `_FLAGS`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True)
class FlagSpec:
    """One fleet-owned `bd create` flag: how to extract and persist it."""

    flag: str  # e.g. "--coder"
    takes_value: bool  # False for a bare switch with no value
    persist_as: str | None  # bd metadata key (e.g. "fleet_coder"), None = not stored
    forward_to_bd: bool  # True = left in argv for bd (fleet only inspects it)
    override_key: str | None  # key in the returned overrides, None = not reported
    allowed: tuple[str, ...] | None = None  # valid values, None = anything goes


_FLAGS: dict[str, FlagSpec] = {
    "coder": FlagSpec("--coder", True, "fleet_coder", False, "coder"),
    "model": FlagSpec("--model", True, "fleet_model", False, "model"),
    "worker": FlagSpec("--worker", True, "fleet_worker", False, "worker"),
    "cwd": FlagSpec("--cwd", True, "fleet_cwd", False, "cwd"),
    "isolation": FlagSpec(
        "--isolation", True, "fleet_isolation", False, "isolation", ("worktree", "none")
    ),
    "job_gate": FlagSpec("--job-gate", True, "fleet_job_gate", False, "job_gate", ("on", "off")),
    "body_file": FlagSpec("--body-file", True, None, True, None),
    "deps": FlagSpec("--deps", True, None, True, None),
}


class CreateOverrides(TypedDict):
    """Per-task overrides extracted from a create argv (cwd always set)."""

    coder: str | None
    model: str | None
    worker: str | None
    cwd: str
    isolation: str | None
    job_gate: str | None


def _extract_flag(args: list[str], flag: str) -> tuple[list[str], str | None]:
    """Strip `--flag <value>` and `--flag=value` from args.

    Returns (new_args, value). If the flag appears multiple times the last
    occurrence wins. A bare `--flag` with no value is dropped silently.
    """
    out: list[str] = []
    value: str | None = None
    eq_prefix = flag + "="
    i = 0
    while i < len(args):
        token = args[i]
        if token == flag:
            if i + 1 < len(args):
                value = args[i + 1]
                i += 2
            else:
                i += 1
            continue
        if token.startswith(eq_prefix):
            value = token[len(eq_prefix) :]
            i += 1
            continue
        out.append(token)
        i += 1
    return out, value


def _extract_switch(args: list[str], flag: str) -> tuple[list[str], bool]:
    """Strip a bare `--flag` switch; return (new_args, present)."""
    out = [token for token in args if token != flag]
    return out, len(out) != len(args)


def _check_allowed(key: str, spec: FlagSpec, value: str | None) -> None:
    """Raise ValueError when a flag value is outside its allowed set."""
    if value is not None and spec.allowed is not None and value not in spec.allowed:
        expected = " or ".join(f"'{item}'" for item in spec.allowed)
        label = spec.flag.lstrip("-")
        raise ValueError(f"Unknown {label} mode {value!r}: expected {expected}")


def rewrite_create_argv(argv: list[str], cwd: str) -> tuple[list[str], CreateOverrides]:
    """Rewrite a `bd create`/`bd new` argv tail, extracting fleet-owned flags.

    Returns (new_argv, overrides). `--cwd` overrides *cwd* (normally the
    shell's cwd at invocation time) as the task's working directory. Raises
    ValueError when a flag value is outside its allowed set.
    """
    values: dict[str, str | bool | None] = {}
    for key, spec in _FLAGS.items():
        if spec.forward_to_bd:
            continue
        if spec.takes_value:
            argv, values[key] = _extract_flag(argv, spec.flag)
        else:
            argv, values[key] = _extract_switch(argv, spec.flag)
        raw_value = values[key]
        _check_allowed(key, spec, raw_value if isinstance(raw_value, str) else None)

    if any(values.values()):
        argv, existing_metadata_raw = _extract_flag(argv, "--metadata")
        try:
            metadata = json.loads(existing_metadata_raw) if existing_metadata_raw else {}
        except (json.JSONDecodeError, ValueError):
            metadata = {}
        for key, spec in _FLAGS.items():
            value = values.get(key)
            if spec.persist_as is not None and value not in (None, False):
                metadata[spec.persist_as] = value
        argv += ["--metadata", json.dumps(metadata)]

    def _str(key: str) -> str | None:
        value = values.get(key)
        return value if isinstance(value, str) else None

    resolved = _str("cwd")
    return argv, {
        "coder": _str("coder"),
        "model": _str("model"),
        "worker": _str("worker"),
        "cwd": resolved if resolved is not None else cwd,
        "isolation": _str("isolation"),
        "job_gate": _str("job_gate"),
    }
