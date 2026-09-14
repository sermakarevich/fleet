"""Tests for the summary_get builder: fetch, chunk, plan/wiki/derive/enrich/index stages."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fleet.workflows.builders import BuildContext, summary_get
from fleet.workflows.builders.chunking import CHUNK_CHARS_DEFAULT, chunk_text, parse_chunk_chars
from fleet.workflows.builders.sources import Source, SourceKind, detect
from fleet.workflows.model import Workflow, ensure_valid

_AT = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
_PAPER_DIR = "{{steps.plan.outputs.paper_dir}}"


def _big_text(headings: int, per_section: int) -> str:
    """Markdown with `headings` sections of about `per_section` characters each."""
    parts = []
    for number in range(1, headings + 1):
        body = ("word " * (per_section // 5)).strip()
        parts.append(f"## Section {number} topic words\n\n{body}")
    return "\n\n".join(parts)


def test_chunk_text_splits_headings_and_preserves_text() -> None:
    """Five ~5.5k sections at target 12000 give 2-4 slugged chunks with all text kept."""
    text = _big_text(5, 5500)
    assert len(text) > 25000  # noqa: PLR2004  # guard: the fixture really is ~30k chars
    chunks = chunk_text(text, 12000)
    assert 2 <= len(chunks) <= 4  # noqa: PLR2004
    assert chunks[0].slug.startswith("01-")
    for position, chunk in enumerate(chunks, start=1):
        assert chunk.slug.startswith(f"{position:02d}-")
    normalize = lambda value: re.sub(r"\s+", "", value)  # noqa: E731
    assert normalize("".join(chunk.text for chunk in chunks)) == normalize(text)


def test_parse_chunk_chars_bounds() -> None:
    """Unset, blank, and garbage inputs fall back to the default; numbers clamp."""
    assert parse_chunk_chars(None) == CHUNK_CHARS_DEFAULT
    assert parse_chunk_chars("abc") == CHUNK_CHARS_DEFAULT
    assert parse_chunk_chars("100") == 2000
    assert parse_chunk_chars("999999") == 60000


def test_detect_routes_by_url() -> None:
    """YouTube, X, arXiv/PDF, and plain article URLs each pick their route."""
    assert detect("https://www.youtube.com/watch?v=abc123") is SourceKind.youtube
    assert detect("https://youtu.be/abc123") is SourceKind.youtube
    assert detect("https://x.com/user/status/123") is SourceKind.x
    assert detect("https://twitter.com/user/status/123") is SourceKind.x
    assert detect("https://arxiv.org/abs/1234.5678") is SourceKind.pdf
    assert detect("https://arxiv.org/pdf/1234.5678") is SourceKind.pdf
    assert detect("https://example.com/some/article") is SourceKind.article


def _ctx(tmp_path: Path, inputs: dict[str, str]) -> BuildContext:
    """Build context rooted at tmp_path for run r1."""
    return BuildContext(run_id="r1", fleet_home=tmp_path, now=_AT, inputs=inputs)


def _workflow() -> Workflow:
    """Bare builder workflow as saved before expansion."""
    return Workflow(id="w", name="summary_get", builder="summary_get", stages=())


def _fake_source() -> Source:
    """Three big sections so the default target yields one chunk step each."""
    return Source(
        url="https://e.com/a",
        kind=SourceKind.article,
        title="T",
        text=_big_text(3, 7000),
        tool="test",
    )


def test_build_expands_five_stages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Build writes source/chunks files and returns the fixed stage graph."""
    monkeypatch.setattr(summary_get, "fetch", lambda url, work_dir: _fake_source())
    result = summary_get.build(_workflow(), _ctx(tmp_path, {"url": "https://e.com/a"}))

    assert [stage.name for stage in result.stages] == ["plan", "wiki", "derive", "enrich", "index"]
    by_name = {stage.name: stage for stage in result.stages}

    plan_steps = by_name["plan"].steps
    assert [step.name for step in plan_steps] == ["plan"]

    wiki_steps = by_name["wiki"].steps
    assert [step.name for step in wiki_steps] == ["chunk-01", "chunk-02", "chunk-03"]
    for step in wiki_steps:
        assert step.needs == ("plan",)

    derive_steps = by_name["derive"].steps
    assert {step.name for step in derive_steps} == {"digest", "summary"}
    chunk_names = tuple(step.name for step in wiki_steps)
    for step in derive_steps:
        assert step.needs == chunk_names

    enrich_steps = by_name["enrich"].steps
    assert [step.name for step in enrich_steps] == [
        "explainer",
        "questions",
        "critical-thinking",
        "connections",
    ]
    for step in enrich_steps:
        assert step.needs == ("digest", "summary")

    index_steps = by_name["index"].steps
    assert [step.name for step in index_steps] == ["index"]
    assert index_steps[0].needs == (
        "explainer",
        "questions",
        "critical-thinking",
        "connections",
    )

    work = tmp_path / "workflows" / "summary_get" / "r1"
    assert (work / "source.md").exists()
    assert list((work / "chunks").glob("01-*.md"))
    assert len(list((work / "chunks").glob("*.md"))) == 3
    manifest = json.loads((work / "chunks.json").read_text(encoding="utf-8"))
    assert [row["slug"][:3] for row in manifest] == ["01-", "02-", "03-"]
    assert [row["index"] for row in manifest] == [1, 2, 3]
    assert all(set(row) == {"index", "slug", "title", "path", "chars"} for row in manifest)

    assert ensure_valid(result) is not None

    steps = [step for stage in result.stages for step in stage.steps]
    for step in steps:
        if step.name == "plan":
            assert _PAPER_DIR not in step.description
            assert "outputs.json" in step.description
        else:
            assert _PAPER_DIR in step.description
    for step in steps:
        assert step.description.endswith("Do not run git. Do not close the bead yourself.")
        assert step.cwd is None and step.coder is None and step.model is None


def test_build_missing_url_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Empty or absent url input fails fast without touching fetch."""
    monkeypatch.setattr(summary_get, "fetch", lambda url, work_dir: _fake_source())
    with pytest.raises(ValueError, match="input url is required"):
        summary_get.build(_workflow(), _ctx(tmp_path, {}))
    with pytest.raises(ValueError, match="input url is required"):
        summary_get.build(_workflow(), _ctx(tmp_path, {"url": "   "}))
