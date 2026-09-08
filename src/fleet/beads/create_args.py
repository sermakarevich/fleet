"""Rewriting for `bd create` / `bd new` argv before it is forwarded to `bd`.

`fleet bd create` intercepts `--coder`, `--model`, `--worker`, `--cwd`, and
`--isolation` instead of forwarding them to `bd` — they become per-task
overrides embedded in `bd`'s own `--metadata`, so they land atomically with
`bd create` before the bead can ever be claimed by the supervisor. See
`queue.py`'s `_task_from_dict` for the read side.
"""

from __future__ import annotations

import json

from fleet.coders import get_coder


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


def rewrite_create_argv(
    argv: list[str], cwd: str
) -> tuple[list[str], dict[str, str | None]]:
    """Rewrite a `bd create`/`bd new` argv tail, extracting --coder/--model/--cwd.

    `--cwd` overrides *cwd* (normally the shell's cwd at invocation time) as
    the task's working directory. `--isolation none` opts the task out of
    git worktree isolation (stored as bd metadata `fleet_isolation`). Returns
    (new_argv, meta) where meta has keys "coder", "model", "worker", "cwd",
    "isolation" (cwd always set; the rest are None unless overridden).
    Raises ValueError if `--coder` names an unknown coder or `--isolation`
    names an unknown mode.
    """
    argv, coder = _extract_flag(argv, "--coder")
    argv, model = _extract_flag(argv, "--model")
    argv, worker = _extract_flag(argv, "--worker")
    argv, cwd_override = _extract_flag(argv, "--cwd")
    argv, isolation = _extract_flag(argv, "--isolation")
    if coder is not None:
        get_coder(coder)  # raises ValueError on an unknown coder name
    if isolation is not None and isolation not in ("worktree", "none"):
        raise ValueError(
            f"Unknown isolation mode {isolation!r}: expected 'worktree' or 'none'"
        )

    resolved_cwd = cwd_override if cwd_override is not None else cwd

    if (
        coder is not None
        or model is not None
        or worker is not None
        or cwd_override is not None
        or isolation is not None
    ):
        argv, existing_metadata_raw = _extract_flag(argv, "--metadata")
        try:
            metadata = json.loads(existing_metadata_raw) if existing_metadata_raw else {}
        except (json.JSONDecodeError, ValueError):
            metadata = {}
        if coder is not None:
            metadata["fleet_coder"] = coder
        if model is not None:
            metadata["fleet_model"] = model
        if worker is not None:
            metadata["fleet_worker"] = worker
        if cwd_override is not None:
            metadata["fleet_cwd"] = cwd_override
        if isolation is not None:
            metadata["fleet_isolation"] = isolation
        argv += ["--metadata", json.dumps(metadata)]

    return argv, {
        "coder": coder,
        "model": model,
        "worker": worker,
        "cwd": resolved_cwd,
        "isolation": isolation,
    }
