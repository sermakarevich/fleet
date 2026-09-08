from __future__ import annotations

import json

import pytest

from fleet.beads.create_args import rewrite_create_argv


def test_no_overrides_passthrough_unchanged() -> None:
    argv, meta = rewrite_create_argv(["create", "Title"], "/cwd")
    assert argv == ["create", "Title"]
    assert meta == {
        "coder": None,
        "model": None,
        "worker": None,
        "cwd": "/cwd",
        "isolation": None,
        "job_gate": None,
    }


def test_extracts_coder_model_cwd_into_metadata() -> None:
    argv, meta = rewrite_create_argv(
        ["create", "Title", "--coder", "claude", "--model", "sonnet", "--cwd", "/custom"],
        "/cwd",
    )
    assert "--coder" not in argv
    assert "--model" not in argv
    assert "--cwd" not in argv
    assert meta == {
        "coder": "claude",
        "model": "sonnet",
        "worker": None,
        "cwd": "/custom",
        "isolation": None,
        "job_gate": None,
    }
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


def test_extracts_isolation_opt_out_into_metadata() -> None:
    argv, meta = rewrite_create_argv(
        ["create", "Title", "--isolation", "none"],
        "/cwd",
    )
    assert "--isolation" not in argv
    assert meta["isolation"] == "none"
    idx = argv.index("--metadata")
    metadata = json.loads(argv[idx + 1])
    assert metadata == {"fleet_isolation": "none"}


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


def test_unknown_isolation_raises_value_error() -> None:
    with pytest.raises(ValueError, match="isolation"):
        rewrite_create_argv(["create", "Title", "--isolation", "docker"], "/cwd")


def test_extracts_job_gate_opt_out_into_metadata() -> None:
    argv, meta = rewrite_create_argv(
        ["create", "Title", "--job-gate", "off"],
        "/cwd",
    )
    assert "--job-gate" not in argv
    assert meta["job_gate"] == "off"
    idx = argv.index("--metadata")
    metadata = json.loads(argv[idx + 1])
    assert metadata == {"fleet_job_gate": "off"}


def test_unknown_job_gate_raises_value_error() -> None:
    with pytest.raises(ValueError, match="job-gate"):
        rewrite_create_argv(["create", "Title", "--job-gate", "maybe"], "/cwd")
