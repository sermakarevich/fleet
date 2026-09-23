"""Recovery script tests: header/chunk parsing, run reconstruction, release sim."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from recover_workflow_runs import (  # noqa: E402
    build_expanded_spec,
    check_release,
    chunks_from_manifest,
    parse_source_header,
    reconstruct_run,
    run_groups,
)

from fleet.workflows.model import Defaults, StepRun, Workflow  # noqa: E402
from fleet.workflows.store import WorkflowStore  # noqa: E402

BASE = Workflow(
    id="wf-hgtt7ao2",
    name="summary_get",
    description="d",
    defaults=Defaults(
        cwd="/tmp/ai", coder="opencode", model="m", priority=2, isolation="none"
    ),
    inputs=(),
    created_at="2026-09-22T00:00:00+00:00",
    updated_at="2026-09-22T00:00:00+00:00",
    builder="summary_get",
)

HEADER = """# Some Owner/Repo
Source: https://github.com/some-owner/some-repo
Kind: repo
Fetched: 2026-09-22T14:00:00+00:00
Tool: git

body here
"""


def _workdir(root: Path, run_id: str) -> Path:
    work = root / "workflows" / "summary_get" / run_id
    (work / "chunks").mkdir(parents=True)
    (work / "source.md").write_text(HEADER, encoding="utf-8")
    records = [
        {
            "index": 1,
            "slug": "01-overview",
            "title": "Overview",
            "path": str(work / "chunks" / "01-overview.md"),
            "chars": 10,
        },
        {
            "index": 2,
            "slug": "02-core",
            "title": "Core",
            "path": str(work / "chunks" / "02-core.md"),
            "chars": 10,
        },
    ]
    (work / "chunks.json").write_text(json.dumps(records), encoding="utf-8")
    (work / "chunks" / "01-overview.md").write_text("# Overview\n", encoding="utf-8")
    (work / "chunks" / "02-core.md").write_text("# Core\n", encoding="utf-8")
    return work


def _bead(
    task_id: str, run_id: str, step: str, status: str, deferred: bool,
    created: str = "2026-09-22T14:00:00Z",
) -> dict:
    return {
        "id": task_id,
        "status": status,
        "labels": ["workflow:wf-hgtt7ao2", f"run:{run_id}", f"step:{step}"],
        "metadata": {
            "fleet_workflow_id": "wf-hgtt7ao2",
            "fleet_workflow_run": run_id,
            "fleet_workflow_step": step,
        },
        "created_at": created,
        "updated_at": created,
        "defer_until": "2026-10-22T14:00:00Z" if deferred else None,
    }


def test_parse_source_header() -> None:
    title, url, kind, tool = parse_source_header(HEADER)
    assert title == "Some Owner/Repo"
    assert url == "https://github.com/some-owner/some-repo"
    assert kind.value == "repo"
    assert tool == "git"
    with pytest.raises(ValueError):
        parse_source_header("no header here\nSource: x\n")


def test_chunks_from_manifest_rejects_slug_skew(tmp_path: Path) -> None:
    work = _workdir(tmp_path, "wfr-test0001")
    records = json.loads((work / "chunks.json").read_text(encoding="utf-8"))
    records[0]["slug"] = "01-wrong"
    with pytest.raises(ValueError, match="slug skew"):
        chunks_from_manifest(work, records)


def test_reconstruct_repo_run(tmp_path: Path) -> None:
    run_id = "wfr-test0001"
    _workdir(tmp_path, run_id)
    (tmp_path / "tasks" / "t-plan").mkdir(parents=True)
    (tmp_path / "tasks" / "t-plan" / "outputs.json").write_text(
        json.dumps({"research_dir": "/tmp/ai/knowledge/research/X", "slug": "X"}),
        encoding="utf-8",
    )
    beads = [
        _bead("t-plan", run_id, "plan", "closed", False),
        _bead("t-w1", run_id, "chunk-01", "open", True),
        _bead("t-w2", run_id, "chunk-02", "open", True),
    ]
    run, infos, expanded, extra = reconstruct_run(
        run_id, beads, BASE, tmp_path, "12000"
    )
    assert run.id == run_id
    assert run.inputs["url"] == "https://github.com/some-owner/some-repo"
    assert run.spec.builder is None
    assert {s.name for st in expanded.stages for s in st.steps} >= {
        "plan", "chunk-01", "chunk-02", "digest", "verify",
    }
    by_step = {i["step_name"]: i for i in infos}
    assert by_step["plan"]["released"] is True
    assert by_step["plan"]["outputs"]["research_dir"] == "/tmp/ai/knowledge/research/X"
    assert by_step["chunk-01"]["released"] is False
    assert by_step["chunk-01"]["stage_index"] == 1
    assert extra == {"missing": ["critical-thinking", "digest", "explainer",
                                 "index", "questions", "summary", "verify"]}


def test_run_groups_keeps_only_live_runs() -> None:
    beads = [
        _bead("t1", "wfr-a", "plan", "closed", False),
        _bead("t2", "wfr-a", "chunk-01", "open", True),
        _bead("t3", "wfr-b", "plan", "closed", False),
    ]
    assert set(run_groups(beads)) == {"wfr-a"}


def test_check_release_ready_wiki_renders(tmp_path: Path) -> None:
    run_id = "wfr-test0001"
    _workdir(tmp_path, run_id)
    (tmp_path / "tasks" / "t-plan").mkdir(parents=True)
    (tmp_path / "tasks" / "t-plan" / "outputs.json").write_text(
        json.dumps({"research_dir": "/tmp/ai/knowledge/research/X", "slug": "X"}),
        encoding="utf-8",
    )
    beads = [
        _bead("t-plan", run_id, "plan", "closed", False),
        _bead("t-w1", run_id, "chunk-01", "open", True),
    ]
    run, infos, _, _ = reconstruct_run(run_id, beads, BASE, tmp_path, "12000")
    store = WorkflowStore(tmp_path / "w.db")
    store.save(BASE)
    store.save_run(run)
    store.save_step_runs(
        [
            StepRun(
                run_id=run.id,
                step_name=i["step_name"],
                stage_index=i["stage_index"],
                task_id=i["task_id"],
                task_status=i["task_status"],
                updated_at=i["updated_at"],
                outputs=i["outputs"],
                released=i["released"],
            )
            for i in infos
        ]
    )
    assert check_release(store, beads) == []
    store.close()


def test_build_expanded_spec_needs_no_fetch(tmp_path: Path) -> None:
    work = _workdir(tmp_path, "wfr-test0001")
    records = json.loads((work / "chunks.json").read_text(encoding="utf-8"))
    chunks = chunks_from_manifest(work, records)
    title, url, kind, tool = parse_source_header(HEADER)
    expanded = build_expanded_spec(BASE, url, kind, title, tool, chunks, work)
    assert str(work) in expanded.stages[0].steps[0].description
    assert len(expanded.stages) == 6
