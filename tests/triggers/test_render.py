"""Tests for trigger template rendering (`{{event.*}}`, `{{trigger.name}}`, `{{n}}`)."""

from __future__ import annotations

from fleet.triggers.model import Trigger, TriggerEvent
from fleet.triggers.render import render

N = 3


def _trigger(**overrides) -> Trigger:
    """One trigger named `watcher` unless overridden."""
    data = {"id": "trg-abc123", "name": "watcher", "source": "blocked_task", "title": "t"}
    data.update(overrides)
    return Trigger.from_dict(data)


def _event(**payload: str) -> TriggerEvent:
    """One event with the given string payload."""
    return TriggerEvent(
        source="blocked_task",
        key="k@1",
        occurred_at="2026-09-09T11:00:00+00:00",
        payload=dict(payload),
    )


def test_event_trigger_n_substitution() -> None:
    """Payload values, the trigger name, and n all fill in."""
    template = "{{event.title}} via {{trigger.name}} #{{n}}"
    got = render(template, trigger=_trigger(), event=_event(title="stuck"), firing_n=N)
    assert got == "stuck via watcher #3"


def test_unknown_placeholder_untouched() -> None:
    """Anything that is not a known placeholder stays as written."""
    template = "{{foo}} {{event.Title}} {{trigger.id}} {{m}}"
    got = render(template, trigger=_trigger(), event=_event(), firing_n=N)
    assert got == template


def test_missing_payload_key_untouched() -> None:
    """A well-formed event key with no payload value stays as written."""
    template = "about {{event.nope}} here"
    assert render(template, trigger=_trigger(), event=_event(), firing_n=N) == template


def test_whitespace_inside_braces() -> None:
    """Spaces around the placeholder name are ignored."""
    template = "{{ event.title }} {{  trigger.name  }} {{ n }}"
    got = render(template, trigger=_trigger(), event=_event(title="stuck"), firing_n=N)
    assert got == "stuck watcher 3"


def test_empty_template() -> None:
    """An empty template renders to an empty string."""
    assert render("", trigger=_trigger(), event=_event(), firing_n=N) == ""
