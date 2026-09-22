"""Tests for workers/research_bodies.py. Mirrors the source path."""

from __future__ import annotations

import pytest

from fleet.workers.research_bodies import KINDS, render_body

FULL_FIELDS: dict[str, dict[str, str]] = {
    "copy": {
        "url": "https://arxiv.org/abs/1234.5678",
        "name": "PaperName",
        "origin": "",
        "target": "/Users/sergii/.ai/knowledge/research/demo",
    },
    "topic_digest": {
        "target": "/Users/sergii/.ai/knowledge/research/demo",
        "nn": "01",
        "subtopic": "memory-types",
        "title": "Memory Types",
        "sources": "PaperA PaperB",
    },
    "agg_digest": {
        "target": "/Users/sergii/.ai/knowledge/research/demo",
        "topic": "Agentic Memory",
        "focus": "How do agents remember?",
    },
    "agg_overview": {
        "target": "/Users/sergii/.ai/knowledge/research/demo",
        "topic": "Agentic Memory",
        "focus": "How do agents remember?",
    },
    "agg_disagreements": {
        "target": "/Users/sergii/.ai/knowledge/research/demo",
        "topic": "Agentic Memory",
        "focus": "How do agents remember?",
    },
    "agg_open_questions": {
        "target": "/Users/sergii/.ai/knowledge/research/demo",
        "topic": "Agentic Memory",
        "focus": "How do agents remember?",
    },
    "lens": {
        "target": "/Users/sergii/.ai/knowledge/research/demo",
        "topic": "Agentic Memory",
        "lens": "tech",
        "audience": "engineer",
    },
    "agg_index": {
        "target": "/Users/sergii/.ai/knowledge/research/demo",
        "topic": "Agentic Memory",
        "focus": "How do agents remember?",
        "lenses": "tech ai",
        "topics": "memory-types retrieval",
    },
}


def test_every_kind_renders_without_placeholders() -> None:
    for kind in KINDS:
        body = render_body(kind, **FULL_FIELDS[kind])
        assert "{{" not in body, kind


def test_render_body_missing_field_raises_keyerror() -> None:
    fields = dict(FULL_FIELDS["copy"])
    del fields["url"]
    with pytest.raises(KeyError):
        render_body("copy", **fields)


def test_agg_digest_contains_verbatim() -> None:
    body = render_body("agg_digest", **FULL_FIELDS["agg_digest"])
    assert "verbatim" in body.lower()


def test_copy_contains_sources_md() -> None:
    body = render_body("copy", **FULL_FIELDS["copy"])
    assert "sources.md" in body


def test_every_template_contains_do_not_run_git() -> None:
    for kind in KINDS:
        body = render_body(kind, **FULL_FIELDS[kind])
        assert "Do not run git" in body, kind
