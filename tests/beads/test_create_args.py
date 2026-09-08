from __future__ import annotations

import json

import pytest

from fleet.beads.create_args import rewrite_create_argv


def test_no_overrides_passthrough_unchanged() -> None:
    argv, meta = rewrite_create_argv(["create", "Title"], "/cwd")
    assert argv == ["create", "Title"]
    assert meta == {"coder": None, "model": None, "worker": None, "cwd": "/cwd"}


def test_extracts_coder_model_cwd_into_metadata() -> None:
    argv, meta = rewrite_create_argv(
        ["create", "Title", "--coder", "claude", "--model", "sonnet", "--cwd", "/custom"],
        "/cwd",
    )
    assert "--coder" not in argv
    assert "--model" not in argv
    assert "--cwd" not in argv
    assert meta == {"coder": "claude", "model": "sonnet", "worker": None, "cwd": "/custom"}
    idx = argv.index("--metadata")
    metadata = json.loads(argv[idx + 1])
    assert metadata == {"fleet_coder": "claude", "fleet_model": "sonnet", "fleet_cwd": "/custom"}


def test_extracts_worker_into_metadata() -> None:
    argv, meta = rewrite_create_argv(
        ["create", "Title", "--worker", "task.fresh"],
        "/cwd",
    )
    assert "--worker" not in argv
    assert meta["worker"] == "task.fresh"
    idx = argv.index("--metadata")
    metadata = json.loads(argv[idx + 1])
    assert metadata == {"fleet_worker": "task.fresh"}


def test_falls_back_to_cwd_when_no_override() -> None:
    _argv, meta = rewrite_create_argv(["create", "Title"], "/shell/cwd")
    assert meta["cwd"] == "/shell/cwd"


def test_merges_with_existing_metadata() -> None:
    argv, meta = rewrite_create_argv(
        ["create", "Title", "--metadata", json.dumps({"foo": "bar"}), "--coder", "codex"],
        "/cwd",
    )
    idx = argv.index("--metadata")
    metadata = json.loads(argv[idx + 1])
    assert metadata == {"foo": "bar", "fleet_coder": "codex"}
    assert meta["coder"] == "codex"


def test_unknown_coder_raises_value_error() -> None:
    with pytest.raises(ValueError):
        rewrite_create_argv(["create", "Title", "--coder", "no-such-coder"], "/cwd")
