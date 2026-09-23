"""Tests for the summarise builder: fetch, chunk, plan/wiki/derive/enrich/index/verify stages."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fleet.workflows.builders import BuildContext, summarise
from fleet.workflows.builders import topics as topics_mod
from fleet.workflows.builders.chunking import CHUNK_CHARS_DEFAULT, chunk_text, parse_chunk_chars
from fleet.workflows.builders.sources import Source, SourceError, SourceKind, detect, fetch
from fleet.workflows.model import Workflow, ensure_valid

_AT = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
_RESEARCH_DIR = "{{steps.plan.outputs.research_dir}}"


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


def test_chunk_text_drops_readme_boilerplate() -> None:
    """Sponsor/License/Star History/TOC sections never become chunks."""
    readme = (
        "# CyberVerse\n\nA virtual world for agents.\n\n"
        + "## Features\n\n" + ("Real-time simulation. " * 200) + "\n\n"
        + "## Sponsor\n\nThanks to Compshare. [Referral](https://example.com/ref)\n\n"
        + "## Star History\n\n[![Star](https://img.shields.io/badge/star-x)]()\n\n"
        + "## License\n\nMIT\n\n"
        + "## Table of Contents\n\n- [Features](#features)\n"
    )
    chunks = chunk_text(readme, 2000)
    assert chunks, "the Features section must survive"
    titles = [chunk.title.lower() for chunk in chunks]
    assert not any("sponsor" in title for title in titles)
    assert not any(title in ("license", "star history", "table of contents") for title in titles)
    assert not any("compshare" in chunk.text.lower() for chunk in chunks)


def test_chunk_text_sponsor_only_yields_no_chunks() -> None:
    """A README with only a Sponsor block yields zero chunks."""
    readme = "# Empty\n\n## Sponsor\n\nThanks to Compshare [link](https://e.com).\n"
    assert chunk_text(readme, 2000) == []


def test_build_fails_when_only_boilerplate_remains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Build fails loudly instead of filing a boilerplate-only source."""
    sponsor_only = Source(
        url="https://e.com/sponsor-only",
        kind=SourceKind.article,
        title="Empty",
        text="# Empty\n\n## Sponsor\n\nThanks to Compshare [link](https://e.com).\n",
        tool="test",
    )
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: sponsor_only)
    with pytest.raises(SourceError, match="boilerplate"):
        summarise.build(_workflow(), _ctx(tmp_path, {"url": "https://e.com/sponsor-only"}))


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


def test_detect_routes_local_files(tmp_path: Path) -> None:
    """Absolute paths and file:// URLs route by suffix; junk is rejected loudly."""
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    md = tmp_path / "notes.md"
    md.write_text("hello world")
    assert detect(str(pdf)) is SourceKind.pdf
    assert detect("file://" + str(pdf)) is SourceKind.pdf
    assert detect(str(md)) is SourceKind.article
    with pytest.raises(SourceError, match="must be"):
        detect(str(tmp_path / "run.exe"))
    with pytest.raises(SourceError, match="must be"):
        detect("not a url")


def test_fetch_local_text_file(tmp_path: Path) -> None:
    """Local .md/.txt files are read off disk without any network."""
    md = tmp_path / "notes.md"
    md.write_text("# Title here\n\n" + "body words " * 100)
    src = fetch(str(md), tmp_path / "work")
    assert src.kind is SourceKind.article
    assert src.tool == "local-file"
    assert "Title here" in src.text
    with pytest.raises(SourceError, match="no such file"):
        fetch(str(tmp_path / "missing.md"), tmp_path / "work")


def _ctx(tmp_path: Path, inputs: dict[str, str]) -> BuildContext:
    """Build context rooted at tmp_path for run r1."""
    return BuildContext(run_id="r1", fleet_home=tmp_path, now=_AT, inputs=inputs)


def _workflow() -> Workflow:
    """Bare builder workflow as saved before expansion."""
    return Workflow(id="w", name="summarise", builder="summarise", stages=())


def _fake_source() -> Source:
    """Three big sections so the default target yields one chunk step each."""
    return Source(
        url="https://e.com/a",
        kind=SourceKind.article,
        title="T",
        text=_big_text(3, 7000),
        tool="test",
    )


def test_build_expands_six_stages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Build writes source/chunks files and returns the fixed stage graph."""
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: _fake_source())
    result = summarise.build(_workflow(), _ctx(tmp_path, {"url": "https://e.com/a"}))

    assert [stage.name for stage in result.stages] == [
        "plan",
        "wiki",
        "derive",
        "enrich",
        "index",
        "verify",
    ]
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
    ]
    for step in enrich_steps:
        assert step.needs == ("digest", "summary")

    index_steps = by_name["index"].steps
    assert [step.name for step in index_steps] == ["index"]
    assert index_steps[0].needs == (
        "explainer",
        "questions",
        "critical-thinking",
    )

    verify_steps = by_name["verify"].steps
    assert [step.name for step in verify_steps] == ["verify"]
    assert verify_steps[0].needs == ("index",)
    assert "blocked" in verify_steps[0].description
    assert "Source:" in verify_steps[0].description

    work = tmp_path / "workflows" / "summarise" / "r1"
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
            assert _RESEARCH_DIR not in step.description
            assert "outputs.json" in step.description
        else:
            assert _RESEARCH_DIR in step.description
    for step in steps:
        assert step.description.endswith("Do not run git. Do not close the bead yourself.")
        assert step.cwd is None and step.coder is None and step.model is None


def test_build_missing_url_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Empty or absent url input fails fast without touching fetch."""
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: _fake_source())
    with pytest.raises(ValueError, match="input url is required"):
        summarise.build(_workflow(), _ctx(tmp_path, {}))
    with pytest.raises(ValueError, match="input url is required"):
        summarise.build(_workflow(), _ctx(tmp_path, {"url": "   "}))


def test_plan_matches_existing_entry_by_provenance_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Plan step searches research/ + investment/ by Source url before deriving a name."""
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: _fake_source())
    result = summarise.build(_workflow(), _ctx(tmp_path, {"url": "https://e.com/a"}))
    plan_desc = next(
        step.description for stage in result.stages if stage.name == "plan" for step in stage.steps
    )
    # Provenance-first: same url reuses the folder no matter the derived slug.
    assert "research/*/source/source.md" in plan_desc
    assert "investment/*/source/source.md" in plan_desc
    assert "no matter what slug" in plan_desc
    # Genuine conflict (different url, same slug) still asks the human.
    assert "Genuine conflict" in plan_desc
    assert plan_desc.count("mcp__ask_human__ask_human_question") >= 2


def test_build_ends_at_verify_with_no_file_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """summarise must not move the entry: the last stage is verify, no file stage."""
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: _fake_source())
    result = summarise.build(_workflow(), _ctx(tmp_path, {"url": "https://e.com/a"}))
    assert result.stages[-1].name == "verify"
    assert [stage.name for stage in result.stages].count("verify") == 1
    assert "file" not in [stage.name for stage in result.stages]
    assert "file" not in [step.name for stage in result.stages for step in stage.steps]


def test_definition_declares_optional_research_target() -> None:
    """Provenance input exists, is optional, and defaults to standalone."""
    inputs = {item["name"]: item for item in summarise.DEFINITION["inputs"]}
    assert "research_target" in inputs
    assert not inputs["research_target"].get("required", False)
    assert inputs["research_target"].get("default") == ""


def test_definition_declares_optional_topic() -> None:
    """Filing input exists, is optional, and defaults to staying in research/."""
    inputs = {item["name"]: item for item in summarise.DEFINITION["inputs"]}
    assert "topic" in inputs
    assert not inputs["topic"].get("required", False)
    assert inputs["topic"].get("default") == ""


def _topics_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake research_topics/ with one topic; build() validates against it."""
    base = tmp_path / "research_topics"
    (base / "voice_agents").mkdir(parents=True)
    monkeypatch.setattr(topics_mod, "research_topics_dir", lambda: base)
    return base


def test_build_with_topic_appends_file_stage_after_verify(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """topic set → a seventh `file` stage depending on verify, moving into the topic."""
    _topics_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: _fake_source())
    result = summarise.build(
        _workflow(),
        _ctx(
            tmp_path,
            {
                "url": "https://e.com/a",
                "research_target": "/Users/sergii/.ai/knowledge/research/demo",
                "topic": "voice_agents",
            },
        ),
    )
    assert [stage.name for stage in result.stages] == [
        "plan",
        "wiki",
        "derive",
        "enrich",
        "index",
        "verify",
        "file",
    ]
    (file_step,) = result.stages[-1].steps
    assert file_step.name == "file"
    assert file_step.needs == ("verify",)
    desc = file_step.description
    assert "research_topics/voice_agents" in desc
    assert "mv " in desc
    assert "already exists" in desc
    assert "confirmation" in desc
    assert "[[<Name>/summary]]" in desc
    assert _RESEARCH_DIR in desc
    assert desc.endswith("Do not run git. Do not close the bead yourself.")
    assert ensure_valid(result) is not None


def test_build_with_topic_rejects_unknown_topic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """topic set to a missing folder fails fast, naming ai new."""
    _topics_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: _fake_source())
    with pytest.raises(ValueError, match="ai new nosuch_topic"):
        summarise.build(
            _workflow(), _ctx(tmp_path, {"url": "https://e.com/a", "topic": "nosuch_topic"})
        )


def test_build_records_research_target_and_topic_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """research_target/topic land in the fetched source header the plan copies on."""
    _topics_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: _fake_source())
    summarise.build(
        _workflow(),
        _ctx(
            tmp_path,
            {
                "url": "https://e.com/a",
                "research_target": "/Users/sergii/.ai/knowledge/research/demo",
                "topic": "voice_agents",
            },
        ),
    )
    header = (tmp_path / "workflows" / "summarise" / "r1" / "source.md").read_text(encoding="utf-8")
    assert "Research-Target: /Users/sergii/.ai/knowledge/research/demo" in header
    assert "Topic: voice_agents" in header


def test_build_without_provenance_writes_no_provenance_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Standalone runs keep the old header shape exactly."""
    monkeypatch.setattr(summarise, "fetch", lambda url, work_dir: _fake_source())
    summarise.build(_workflow(), _ctx(tmp_path, {"url": "https://e.com/a"}))
    header = (tmp_path / "workflows" / "summarise" / "r1" / "source.md").read_text(encoding="utf-8")
    assert "Research-Target:" not in header
    assert "Topic:" not in header


def test_fetch_strips_nul_bytes_from_local_file(tmp_path: Path) -> None:
    """NUL bytes in fetched text (e.g. pdftotext layout output) never reach chunks."""
    md = tmp_path / "notes.md"
    md.write_text("# Title here\n\n" + "body \x00words " * 100)
    src = fetch(str(md), tmp_path / "work")
    assert "\x00" not in src.title
    assert "\x00" not in src.text
    assert "Title here" in src.text


def test_chunk_text_strips_nul_bytes_from_derived_titles() -> None:
    """Chunk titles derived from NUL-carrying text are subprocess-argv safe."""
    text = ("\x00$\x00F word " * 300) + "\n\n" + ("more words " * 300)
    chunks = chunk_text(text, 2000)
    assert len(chunks) == 2  # noqa: PLR2004  # guard: title comes from first words, not a heading
    for chunk in chunks:
        assert "\x00" not in chunk.title


def test_build_with_nul_bytes_yields_subprocess_safe_steps(tmp_path: Path) -> None:
    """Regression: src-06 was skipped with 'embedded null byte' at spawn.

    A NUL in a chunk-derived step title raises ValueError when the runner
    passes it to the bead CLI through subprocess argv, which the spawn step
    journals as a skipped child. End to end through the real fetch, no step
    title or description may carry a NUL.
    """
    md = tmp_path / "paper.md"
    md.write_text(
        ("body \x00words " * 100) + "\n\n" + ("more words " * 100) + "\n\n" + ("end words " * 100)
    )
    result = summarise.build(_workflow(), _ctx(tmp_path, {"url": str(md)}))
    steps = [step for stage in result.stages for step in stage.steps]
    assert steps
    for step in steps:
        assert "\x00" not in step.title
        assert "\x00" not in step.description
    assert ensure_valid(result) is not None
