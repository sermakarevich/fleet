"""Spawn-time source resolution (fleet-2u7jk).

When a src-NN workflow child is skipped at spawn, dependent bead bodies
must stop naming it (or the digest waits forever and loops partial), and
dependents of workflow children must carry the data to resolve the real
filed folder name (design-time guesses differ from the summarise plan
slug). Covers ``workers/job.py`` SpawnChildren + ``research_bodies``
helpers.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import structlog

from fleet.core.config import RuntimeConfig
from fleet.core.job_plan import validate_tasks
from fleet.core.task import Task
from fleet.state import paths as state_paths
from fleet.workers.base import StepContext, StepStatus
from fleet.workers.job import SOURCES_RESOLVED, SpawnChildren
from fleet.workers.research_bodies import (
    SOURCES_NOTE_HEADER,
    SourceRow,
    build_sources_note,
    resolve_folder,
    strip_names_from_lists,
)


class FakeQueue:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict]] = []
        self.comments: list[tuple[str, str]] = []
        self.updated: list[tuple[str, str]] = []

    def list_children(self, epic_id: str):
        return []

    def create_child(self, epic_id: str, spec: dict):
        child_id = f"kid-{len(self.created) + 1}"
        self.created.append((epic_id, spec))
        return SimpleNamespace(id=child_id)

    def add_dependency(self, epic_id: str, child_id: str) -> None:
        return None

    def comment(self, task_id: str, body: str) -> None:
        self.comments.append((task_id, body))

    def update_task(self, task_id: str, *, description: str | None = None, **kwargs) -> None:
        self.updated.append((task_id, description or ""))


class FakeRunner:
    """Workflow starter: ValueError (skip) for urls containing 'bad'."""

    def start(self, workflow_ref: str, inputs):
        url = inputs.get("url", "")
        if "bad" in url:
            raise ValueError("embedded null byte")
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return SimpleNamespace(
            run_id=f"wfr-{slug}",
            task_ids=(f"plan-{slug}", f"file-{slug}"),
            final_task_ids=(f"file-{slug}",),
        )


def _ctx(tmp_path: Path) -> StepContext:
    task_dir = state_paths.task_dir(tmp_path, "job-1")
    task_dir.mkdir(parents=True, exist_ok=True)
    return StepContext(
        task=Task(
            id="job-1",
            title="job",
            description="goal",
            status="in_progress",
            type="epic",
            worker="job",
        ),
        task_dir=task_dir,
        workdir=tmp_path,
        fleet_home=tmp_path,
        coder=None,  # type: ignore[arg-type]
        config=RuntimeConfig(),
        rate_gauge=None,  # type: ignore[arg-type]
        log=structlog.get_logger(),
        workflow_runner=FakeRunner(),  # type: ignore[arg-type]
    )


def _write_tasks(ctx: StepContext, doc: dict) -> None:
    artifacts = ctx.task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "tasks.json").write_text(json.dumps(doc))


_DIGEST_BODY = """Write the digest for sub-topic `T` (`s`).

Fresh sources: read ONLY the summaries for each `<Name>` in
`GuessBad GuessGood` (space-separated folder names).

## Sources in this sub-topic
| source | kind | what it contributes |
"""


def _research_tasks() -> dict:
    return {
        "tasks": [
            {
                "key": "src-06",
                "title": "summarise: bad paper",
                "workflow": "summarise",
                "inputs": {"url": "https://x/bad-paper"},
                "folder": "GuessBad",
            },
            {
                "key": "src-07",
                "title": "summarise: good paper",
                "workflow": "summarise",
                "inputs": {"url": "https://x/good-paper"},
                "folder": "GuessGood",
            },
            {
                "key": "topic-02",
                "title": "digest: s",
                "body": _DIGEST_BODY,
                "cwd": "/Users/sergii/.ai",
                "depends_on": ["src-06", "src-07"],
            },
        ]
    }


def test_skipped_src_removed_from_dependent_body_with_note(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, _research_tasks())
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK

    skipped = json.loads(
        (ctx.task_dir / "artifacts" / "children_skipped.json").read_text(encoding="utf-8")
    )
    assert skipped == {"src-06": "embedded null byte"}

    # The digest depended on the skipped run's final tasks minus the skip.
    digest_spec = queue.created[0][1]
    assert digest_spec["title"] == "digest: s"
    assert digest_spec["depends_on"] == ["file-good-paper"]

    # Body rewritten: skipped name gone from the source list, note present.
    assert queue.updated, "dependent body must be rewritten via update_task"
    new_body = queue.updated[0][1]
    assert "GuessBad GuessGood" not in new_body
    assert "`GuessGood`" in new_body
    assert "skipped: embedded null byte" in new_body
    assert SOURCES_NOTE_HEADER in new_body
    assert "https://x/bad-paper" in new_body

    # Manifest records both keys.
    manifest = json.loads(
        (ctx.task_dir / "artifacts" / SOURCES_RESOLVED).read_text(encoding="utf-8")
    )
    assert manifest["src-06"]["state"] == "skipped"
    assert manifest["src-06"]["folder"] == "GuessBad"
    assert manifest["src-07"]["state"] == "ready"
    assert manifest["src-07"]["run_id"] == "wfr-good-paper"

    # Job comment records the skip and the rewrite.
    assert "src-06" in queue.comments[0][1]
    assert "rewrote 1 dependent" in queue.comments[0][1]


def test_no_skip_still_appends_resolution_table(tmp_path: Path) -> None:
    doc = _research_tasks()
    for task in doc["tasks"]:
        if task.get("workflow"):
            task["inputs"] = {"url": task["inputs"]["url"].replace("bad-paper", "ok-paper")}
    ctx = _ctx(tmp_path)
    _write_tasks(ctx, doc)
    queue = FakeQueue()
    result = asyncio.run(SpawnChildren(queue).run(ctx))
    assert result.status == StepStatus.OK
    assert queue.updated, "digest should still get the resolution table"
    new_body = queue.updated[0][1]
    assert "GuessBad GuessGood" in new_body  # nothing stripped
    assert SOURCES_NOTE_HEADER in new_body
    assert "ready (run wfr-" in new_body


def test_strip_names_from_lists_units() -> None:
    body, removed = strip_names_from_lists("in `A B C` end", {"B"})
    assert body == "in `A C` end"
    assert removed == {"B"}

    body, removed = strip_names_from_lists("in `A B` and `B C`", {"B"})
    assert body == "in `A` and `C`"
    assert removed == {"B"}

    # Substring safety: Foo must not match FooBar.
    body, removed = strip_names_from_lists("in `Foo FooBar`", {"Foo"})
    assert body == "in `FooBar`"
    assert removed == {"Foo"}

    # Path spans are single items: untouched.
    body, removed = strip_names_from_lists("read `research_topics/t/Foo/summary.md`", {"Foo"})
    assert removed == set()

    # Empty remainder points at the note.
    body, removed = strip_names_from_lists("in `Foo`", {"Foo"})
    assert "Source resolution" in body
    assert removed == {"Foo"}

    # No names: body identical.
    body, removed = strip_names_from_lists("in `A`", set())
    assert body == "in `A`" and removed == set()


def test_build_sources_note_marks_skipped() -> None:
    note = build_sources_note(
        [
            SourceRow(
                key="src-06",
                title="t",
                folder="GuessBad",
                url="https://x/6",
                status="skipped: embedded null byte",
                skipped=True,
            )
        ],
        "/jobs/job-1/artifacts/sources_resolved.json",
    )
    assert note.startswith(SOURCES_NOTE_HEADER)
    assert "skipped: embedded null byte" in note


def test_resolve_folder_prefers_provenance_over_guess(tmp_path: Path) -> None:
    topic = tmp_path / "research_topics" / "demo"
    real = topic / "NaturalLanguageKnowledgeGraphQueryExecution"
    (real / "source").mkdir(parents=True)
    (real / "source" / "source.md").write_text(
        "# src\nSource: https://x/paper\n", encoding="utf-8"
    )
    (real / "summary.md").write_text("summary https://x/paper", encoding="utf-8")

    resolved = resolve_folder(
        topic,
        "https://x/paper",
        "NaturalLanguageKnowledgeGraphQueryExecutionLeveragingControlledSemantics",
    )
    assert resolved == "NaturalLanguageKnowledgeGraphQueryExecution"

    # Unknown url falls back to an existing guessed folder.
    (topic / "GuessGood").mkdir()
    assert resolve_folder(topic, "https://x/unknown", "GuessGood") == "GuessGood"

    # Nothing matches: None (caller reports unreachable, never pending).
    assert resolve_folder(topic, "https://x/unknown", "Nope") is None
    assert resolve_folder(topic, None, None) is None


def test_design_folder_field_passes_validation() -> None:
    assert validate_tasks(_research_tasks(), max_children=30) == []
