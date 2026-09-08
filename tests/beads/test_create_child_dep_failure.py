"""create_child raises when `bd dep add` fails (no swallowed orphan)."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet.beads.client import BdError
from fleet.beads.queue import BeadsQueue


def _ok() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["bd"], returncode=0, stdout="", stderr="")


@contextmanager
def _patched_client(
    queue: BeadsQueue, dep_add_error: BaseException | None
) -> Iterator[list[list[str]]]:
    """Patch BdClient with an in-memory show/create and a configurable dep add."""
    bodies = {
        "epic-1": {"id": "epic-1", "title": "Epic", "description": None, "status": "open"},
        "kid-1": {"id": "kid-1", "title": "Kid", "description": None, "status": "open"},
    }
    runs: list[list[str]] = []

    def fake_run_json(argv: list[str], **kwargs: object) -> object:
        if argv[0] == "show":
            return dict(bodies[argv[1]])
        if argv[0] == "create":
            return {"id": "kid-1"}
        raise AssertionError(f"unexpected bd argv: {argv}")

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        runs.append(argv)
        if argv[:2] == ["dep", "add"] and dep_add_error is not None:
            raise dep_add_error
        return _ok()

    with (
        patch.object(queue._client, "run_json", side_effect=fake_run_json),
        patch.object(queue._client, "run", side_effect=fake_run),
    ):
        yield runs


def test_create_child_raises_when_dep_add_fails(tmp_path: Path) -> None:
    """A failed `bd dep add` raises BdError so the caller sees the orphan."""
    q = BeadsQueue(repo_root=tmp_path)
    with (
        _patched_client(q, BdError("dep add failed", stderr="boom", returncode=1)),
        pytest.raises(BdError, match="dep add failed"),
    ):
        q.create_child("epic-1", {"title": "Kid"})


def test_create_child_links_epic_to_child_on_success(tmp_path: Path) -> None:
    """On success the epic gains a dependency on the new child bead."""
    q = BeadsQueue(repo_root=tmp_path)
    with _patched_client(q, None) as runs:
        child = q.create_child("epic-1", {"title": "Kid"})
    assert child.id == "kid-1"
    assert ["dep", "add", "epic-1", "kid-1"] in runs
