"""Tests for fleet.flows.templates."""

from __future__ import annotations

from typing import Any

import pytest

from fleet.core.errors import TemplateError
from fleet.flows import templates


def _sample_context() -> dict[str, Any]:
    """Build a context shaped like fleet.runs.state output."""
    return {
        "inputs": {"repo": "/tmp/demo", "feature": "login"},
        "steps": {"r": {"outputs": {"units": [{"unit": "M1"}, {"unit": "R1"}]}}},
        "item": {"unit": "M1"},
        "index": 0,
        "run": {"id": "abc", "date": "2026-09-27"},
        "defaults": {"model": "base-model"},
        "args": {},
        "flag": True,
    }


def test_plain_text_passes_through() -> None:
    """Unmarked text renders unchanged."""
    assert templates.render("hello world", _sample_context()) == "hello world"


def test_inputs_template_renders() -> None:
    """A dotted lookup renders from the context."""
    assert templates.render("repo {{ inputs.repo }}", _sample_context()) == "repo /tmp/demo"


def test_is_template_markers() -> None:
    """is_template spots {{ and {% but not plain text."""
    assert templates.is_template("{{ inputs.repo }}")
    assert templates.is_template("{% if flag %}x{% endif %}")
    assert not templates.is_template("plain text")


def test_missing_name_raises_template_error_mentioning_template() -> None:
    """StrictUndefined failures surface as TemplateError naming the template."""
    text = "{{ inputs.missing }}"
    with pytest.raises(TemplateError, match="inputs.missing"):
        templates.render(text, _sample_context())


def test_render_value_returns_list_object() -> None:
    """A lone expression returns the Python value, not a string."""
    units = templates.render_value("{{ steps.r.outputs.units }}", _sample_context())
    assert units == [{"unit": "M1"}, {"unit": "R1"}]
    assert isinstance(units, list)


def test_render_value_mixed_text_returns_str() -> None:
    """Text around an expression falls back to plain rendering."""
    value = templates.render_value("x {{ inputs.repo }}", _sample_context())
    assert value == "x /tmp/demo"
    assert isinstance(value, str)


def test_render_value_default_filter_missing_key() -> None:
    """default([]) rescues a missing item key under StrictUndefined."""
    context = dict(_sample_context(), item={"unit": "M1"})
    assert templates.render_value("{{ item.after | default([]) }}", context) == []


def test_map_attribute_list_filter() -> None:
    """Jinja built-in map(attribute=...)|list works over step outputs."""
    value = templates.render_value(
        '{{ steps.r.outputs.units | map(attribute="unit") | list }}',
        _sample_context(),
    )
    assert value == ["M1", "R1"]


def test_render_bool_values() -> None:
    """Bools pass through; on/flag render True; False stays False."""
    context = _sample_context()
    assert templates.render_bool(True, context) is True
    assert templates.render_bool(False, context) is False
    assert templates.render_bool("on", context) is True
    assert templates.render_bool("{{ flag }}", context) is True


def test_render_bool_unknown_word_raises() -> None:
    """An unrecognised word is a TemplateError, not a guess."""
    with pytest.raises(TemplateError):
        templates.render_bool("maybe", _sample_context())


def test_render_mapping_renders_each_value() -> None:
    """Every mapping value is rendered over the context."""
    result = templates.render_mapping(
        {"cwd": "{{ inputs.repo }}", "fixed": "yes"}, _sample_context()
    )
    assert result == {"cwd": "/tmp/demo", "fixed": "yes"}


def test_sandbox_escape_raises_template_error() -> None:
    """Dunder access is blocked by the sandbox and wrapped as TemplateError."""
    with pytest.raises(TemplateError):
        templates.render("{{ ''.__class__ }}", _sample_context())
